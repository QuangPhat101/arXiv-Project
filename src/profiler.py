"""Resource Profiler and Performance Monitor for arXiv Crawler.

Provides real-time resource tracking (RAM, CPU) via periodic background sampling
and micro-timing across scraping pipeline phases (discovery, download, extract, s2, sleep).
Outputs structured benchmark reports (JSON) and terminal summary tables.
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


class CrawlerProfiler:
    """Monitors process resource consumption and phase timings during crawling."""

    def __init__(self, sample_interval: float = 1.0) -> None:
        """Initialize profiler with a sampling interval in seconds."""
        self.sample_interval = sample_interval
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._start_wall_time = 0.0
        self._end_wall_time = 0.0

        # Time series data
        self.timestamps: List[float] = []
        self.ram_samples_mb: List[float] = []
        self.cpu_samples_pct: List[float] = []

        # Cumulative phase durations in seconds
        self.phase_times: Dict[str, float] = {
            "discovery": 0.0,
            "download": 0.0,
            "extract": 0.0,
            "s2_references": 0.0,
            "rate_limit_sleep": 0.0,
        }
        self._phase_lock = threading.Lock()

        # Per-paper records
        self.paper_records: List[Dict[str, Any]] = []

    def start(self) -> None:
        """Start the background monitoring thread and wall timer."""
        self._start_wall_time = time.perf_counter()
        if psutil is not None:
            self._monitoring = True
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

    def stop(self) -> None:
        """Stop background sampling and record final wall time."""
        self._end_wall_time = time.perf_counter()
        self._monitoring = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)

    def _monitor_loop(self) -> None:
        """Background thread loop sampling RSS RAM and CPU utilization."""
        if psutil is None:
            return

        process = psutil.Process(os.getpid())
        t0 = self._start_wall_time

        while self._monitoring:
            try:
                # Sum RSS of current process and all child processes
                rss_bytes = process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        rss_bytes += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                rss_mb = round(rss_bytes / (1024 * 1024), 2)
                cpu_pct = round(process.cpu_percent(interval=None), 1)
                elapsed = round(time.perf_counter() - t0, 1)

                self.timestamps.append(elapsed)
                self.ram_samples_mb.append(rss_mb)
                self.cpu_samples_pct.append(cpu_pct)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            time.sleep(self.sample_interval)

    @contextmanager
    def time_phase(self, phase_name: str):
        """Context manager to measure execution time of a specific pipeline phase."""
        t_start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - t_start
            with self._phase_lock:
                if phase_name not in self.phase_times:
                    self.phase_times[phase_name] = 0.0
                self.phase_times[phase_name] += duration

    def record_paper(
        self,
        arxiv_id: str,
        duration: float,
        raw_bytes: int,
        extracted_bytes: int,
        status: str,
        phase_times: Optional[Dict[str, float]] = None,
    ) -> None:
        """Record telemetry for a single completed paper, including per-phase breakdown."""
        current_ram_mb = 0.0
        if psutil is not None:
            try:
                current_ram_mb = round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)
            except Exception:
                pass

        record: Dict[str, Any] = {
            "arxiv_id": arxiv_id,
            "duration_s": round(duration, 2),
            "raw_bytes": raw_bytes,
            "extracted_bytes": extracted_bytes,
            "status": status,
            "ram_mb": current_ram_mb,
        }
        if phase_times:
            record["phases_s"] = {k: round(v, 2) for k, v in phase_times.items()}

        self.paper_records.append(record)

    def get_summary(self) -> Dict[str, Any]:
        """Aggregate all collected telemetry into a structured dictionary."""
        wall_time = self._end_wall_time - self._start_wall_time
        if wall_time <= 0:
            wall_time = time.perf_counter() - self._start_wall_time

        peak_ram = max(self.ram_samples_mb) if self.ram_samples_mb else 0.0
        avg_ram = (sum(self.ram_samples_mb) / len(self.ram_samples_mb)) if self.ram_samples_mb else 0.0

        total_raw = sum(r["raw_bytes"] for r in self.paper_records)
        total_ext = sum(r["extracted_bytes"] for r in self.paper_records)
        savings_pct = round((1 - total_ext / total_raw) * 100, 2) if total_raw > 0 else 0.0

        n_papers = len(self.paper_records)
        avg_time = round(wall_time / n_papers, 2) if n_papers > 0 else 0.0

        # Sample timeline if large to keep JSON lightweight
        step = max(1, len(self.timestamps) // 200)

        return {
            "testbed": {
                "platform": platform.platform(),
                "system": platform.system(),
                "cpu_cores": os.cpu_count() or 1,
                "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 2) if psutil else None,
                "python_version": platform.python_version(),
            },
            "run_summary": {
                "evaluated_papers": n_papers,
                "wall_time_s": round(wall_time, 2),
                "wall_time_min": round(wall_time / 60, 2),
                "avg_time_per_paper_s": avg_time,
                "success_count": sum(1 for r in self.paper_records if "SUCCESS" in r["status"]),
                "pdf_only_count": sum(1 for r in self.paper_records if "PDF_ONLY" in r["status"]),
                "failed_count": sum(1 for r in self.paper_records if "FAILED" in r["status"]),
            },
            "memory": {
                "peak_ram_mb": peak_ram,
                "avg_ram_mb": round(avg_ram, 2),
                "sample_count": len(self.ram_samples_mb),
                "timeline_s": self.timestamps[::step],
                "ram_timeline_mb": self.ram_samples_mb[::step],
                "cpu_timeline_pct": self.cpu_samples_pct[::step],
            },
            "storage": {
                "total_raw_bytes": total_raw,
                "total_extracted_bytes": total_ext,
                "total_raw_mb": round(total_raw / (1024 * 1024), 2),
                "total_extracted_mb": round(total_ext / (1024 * 1024), 2),
                "storage_savings_pct": savings_pct,
            },
            "phase_breakdown_s": {k: round(v, 2) for k, v in self.phase_times.items()},
            "paper_records": self.paper_records,
        }

    def print_summary_table(self) -> None:
        """Print a formatted benchmark summary table to stdout."""
        summary = self.get_summary()
        run = summary["run_summary"]
        mem = summary["memory"]
        stor = summary["storage"]
        phases = summary["phase_breakdown_s"]

        print("\n" + "=" * 65)
        print("          BENCHMARK PROFILER SUMMARY REPORT          ")
        print("=" * 65)
        print(f" Evaluated Papers:        {run['evaluated_papers']}")
        print(f" Total Wall-clock Time:   {run['wall_time_s']} s ({run['wall_time_min']} mins)")
        print(f" Average Time per Paper:  {run['avg_time_per_paper_s']} s")
        print(f" Peak Memory (RSS):       {mem['peak_ram_mb']:.1f} MB")
        print(f" Average Memory (RSS):    {mem['avg_ram_mb']:.1f} MB")
        print(f" Total Raw Download:      {stor['total_raw_mb']:.2f} MB")
        print(f" Total Extracted (.tex):  {stor['total_extracted_mb']:.2f} MB")
        print(f" Storage Savings:         {stor['storage_savings_pct']:.1f} %")
        print("-" * 65)
        print(" Phase Duration Breakdown:")
        total_phase = sum(phases.values()) or 1.0
        for phase, dur in phases.items():
            pct = (dur / total_phase) * 100
            print(f"   - {phase:<18}: {dur:>6.1f} s  ({pct:>5.1f}%)")
        print("=" * 65 + "\n", flush=True)

    def export_json(self, output_path: Path | str) -> Path:
        """Save benchmark telemetry to JSON file."""
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = self.get_summary()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return target

