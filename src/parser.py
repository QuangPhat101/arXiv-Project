import hashlib
import re
from pathlib import Path

# \input{x} or the brace-less \input x; (?![a-zA-Z]) skips \includegraphics, \inputencoding, ...
INPUT_RE = re.compile(r'\\(?:input|include|subfile)(?![a-zA-Z])\s*(?:\{([^}]+)\}|([^\s{}\\]+))')
# shortcut: titles with nested braces get cut; upgrade to a brace-matching scan if it shows up often
SEC_RE = re.compile(r'\\(chapter|section|subsection|subsubsection)\*?\{([^}]*)\}')
LEVEL = {'chapter': 1, 'section': 2, 'subsection': 3, 'subsubsection': 4}
# (?!\}) skips macro definitions like \newcommand{\bdoc}{\begin{document}}
BODY_RE = re.compile(r'\\begin\{document\}(?!\})(.*?)\\end\{document\}(?!\})', re.S)
PROTECT_RE = re.compile(
    r'\$\$.*?\$\$|\$.*?\$|\\\(.*?\\\)|\\url\{[^}]*\}|https?://\S*[^\s.,;)]|\\(?:cite|ref|eqref|label)\w*\{[^}]*\}', re.S)
ABBR = ['Fig.', 'Figs.', 'Eq.', 'Eqs.', 'Sec.', 'Tab.', 'et al.', 'i.e.', 'e.g.', 'vs.', 'etc.', 'cf.', 'resp.', 'Ref.']

ENV_KIND = {'figure': 'figure', 'table': 'table', 'equation': 'equation', 'align': 'equation'}
ENV_RE = re.compile(r'\\begin\{(figure|table|equation|align)\*?\}.*?\\end\{\1\*?\}', re.S)
CMD_RE = re.compile(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})*')


def is_prose(sentence):
    """True if at least 3 real words remain after removing LaTeX commands (and their arguments)."""
    return len(re.findall(r'[A-Za-z]{2,}', CMD_RE.sub(' ', sentence))) >= 3

def strip_comments(text):
    return re.sub(r'(?<!\\)%.*', '', text)


def find_main_tex(vdir):
    """Pick the file whose expanded text (after following \\input) has the longest document body.

    Folders often hold leftover templates or cover letters with their own \\begin{document};
    \\documentclass or \\begin{document} may also live in an \\input-ed file, so the main file
    is only identifiable after expansion.
    """
    best, best_len = None, -1
    for p in sorted(Path(vdir).rglob('*.tex')):
        raw = strip_comments(p.read_text(errors='ignore'))
        if r'\documentclass' not in raw and r'\begin{document}' not in raw and r'\end{document}' not in raw:
            continue
        m = BODY_RE.search(expand_inputs(p, p.parent))
        if m and len(m.group(1)) > best_len:
            best, best_len = p, len(m.group(1))
    return best


def expand_inputs(path, root, seen=None):
    seen = set() if seen is None else seen
    if path in seen or not path.exists():
        return ''
    seen.add(path)
    text = strip_comments(path.read_text(errors='ignore'))

    def repl(m):
        p = root / (m.group(1) or m.group(2)).strip()
        # \subfile targets are standalone documents: keep only their body
        return extract_body(expand_inputs(p if p.suffix == '.tex' else Path(str(p) + '.tex'), root, seen))
    return INPUT_RE.sub(repl, text)


def extract_body(tex):
    m = BODY_RE.search(tex)
    return m.group(1) if m else tex


def split_sentences(text):
    saved = []

    def hide(m):
        saved.append(m.group(0))
        return f'\x00{len(saved) - 1}\x00'
    text = PROTECT_RE.sub(hide, text)
    for a in ABBR:
        text = text.replace(a, a.replace('.', '\x01'))
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z\\\x00])', ' '.join(text.split()))
    out = []
    for p in parts:
        p = re.sub(r'\x00(\d+)\x00', lambda m: saved[int(m.group(1))], p.replace('\x01', '.')).strip()
        if p:
            out.append(p)
    return out


def make_id(arxiv_id, kind, content):
    return f"{arxiv_id}#{hashlib.sha1(f'{kind}|{content}'.encode()).hexdigest()[:12]}"


def parse_version(vdir, arxiv_id, version):
    main = find_main_tex(vdir)
    if main is None:  # PDF-only version
        return [], []
    body = extract_body(expand_inputs(main, main.parent))
    elements, hierarchy = {}, []

    def add(kind, content, parent):
        eid = make_id(arxiv_id, kind, content)
        elements[eid] = (eid, arxiv_id, kind, content)
        hierarchy.append((arxiv_id, version, eid, parent))
        return eid

    def add_text(text, parent):
        def pull_env(m):
            add(ENV_KIND[m.group(1)], m.group(0).strip(), parent)
            return '\n\n'
        text = ENV_RE.sub(pull_env, text)
        for para in re.split(r'\n\s*\n', text):
            for s in split_sentences(para):
                if is_prose(s):
                    add('sentence', s, parent)

    root = add('document', arxiv_id, arxiv_id)
    stack = [(0, root)]
    pieces = SEC_RE.split(body)
    add_text(pieces[0], root)
    for i in range(1, len(pieces), 3):
        cmd, title, text = pieces[i:i + 3]
        while stack[-1][0] >= LEVEL[cmd]:
            stack.pop()
        sid = add(cmd, title.strip(), stack[-1][1])
        stack.append((LEVEL[cmd], sid))
        add_text(text, sid)
    return list(elements.values()), hierarchy
