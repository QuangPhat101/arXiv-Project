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

FLOAT_RE = re.compile(r'\\begin\{(figure|table)\*?\}.*?\\end\{\1\*?\}', re.S)
# Display math in all its equivalent spellings; (?<!\\) skips the \\[2pt] line-break form.
MATH_RE = re.compile(
    r'\\begin\{(equation|align|gather|multline|eqnarray|displaymath)(\*?)\}(.*?)\\end\{\1\2\}'
    r'|(?<!\\)\\\[(.*?)\\\]|\$\$(.*?)\$\$', re.S)
LIST_RE = re.compile(r'\\(begin|end)\{(itemize|enumerate|description)\}|\\item\b(?:\s*\[[^\]]*\])?')
CMD_RE = re.compile(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})*')
CITE_RE = re.compile(r'(\\cite[a-zA-Z]*\*?(?:\[[^\]]*\]){0,2})\{([^}]*)\}')
# Bibliography is stored in the bibtex table, not in the content tree.
BIB_RE = re.compile(r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}'
                    r'|\\(?:bibliography|bibliographystyle|addbibresource)\{[^}]*\}|\\printbibliography(?:\[[^\]]*\])?', re.S)
BIB_TITLES = {'references', 'reference', 'bibliography'}
# Formatting that does not change meaning: \textbf{x} -> x, {\bf x} -> x.
FORMAT_RE = re.compile(r'\\(?:textbf|textit|textsl|textsc|textrm|textsf|textnormal|emph|underline)\{([^{}]*)\}'
                       r'|\{\\(?:bf|it|em|sl|sc|rm|sf)\s+([^{}]*)\}')
SPACING_RE = re.compile(r'\\(?:noindent|centering|smallskip|medskip|bigskip|newline|linebreak)\b'
                        r'|\\[vh]space\*?\{[^}]*\}|\\\\(?:\[[^\]]*\])?')


def is_prose(sentence):
    """True if at least 3 real words remain after removing LaTeX commands (and their arguments)."""
    return len(re.findall(r'[A-Za-z]{2,}', CMD_RE.sub(' ', sentence))) >= 3


def clean_text(text):
    """Drop formatting that does not change meaning, so v1/v2 differing only in markup dedup."""
    prev = None
    while prev != text:  # nested \textbf{\emph{x}} needs several passes
        prev, text = text, FORMAT_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)
    text = SPACING_RE.sub(' ', text).replace('~', ' ')
    return ' '.join(text.split())


def normalize_math(body):
    """Canonical form of a display formula: no labels/numbering, whitespace only where TeX needs it."""
    body = re.sub(r'\\label\{[^}]*\}|\\nonumber\b|\\notag\b', '', body).strip()
    # Keep one space only after a control word followed by a letter (\alpha x); TeX ignores the rest.
    return re.sub(r'(\\[a-zA-Z]+)?\s+(?=(.))',
                  lambda m: (m.group(1) + ' ') if m.group(1) and m.group(2).isalpha() else (m.group(1) or ''),
                  body)


def canonical_cites(text, cite_map=None):
    """Rewrite \\cite keys to their canonical key (cite_map: original key -> canonical key)."""
    cite_map = cite_map or {}

    def repl(m):
        keys = [k.strip() for k in m.group(2).split(',') if k.strip()]
        return m.group(1) + '{' + ','.join(cite_map.get(k, k) for k in keys) + '}'
    return CITE_RE.sub(repl, text)


def split_lists(text):
    """Split text into (outside_text, [list_bodies]) for top-level itemize/enumerate/description."""
    outside, lists, depth, start, last = [], [], 0, 0, 0
    for m in LIST_RE.finditer(text):
        if m.group(1) == 'begin':
            if depth == 0:
                start = m.end()
            depth += 1
        elif m.group(1) == 'end' and depth:
            depth -= 1
            if depth == 0:
                outside.append(text[last:text.rfind('\\begin', last, start)] + '\n\n')
                lists.append(text[start:m.start()])
                last = m.end()
    outside.append(text[last:])  # an unclosed list stays as plain text rather than being lost
    return ''.join(outside), lists


def split_items(body):
    """Split a list body at its own top-level \\item markers (nested lists stay inside their item)."""
    items, depth, cur = [], 0, None
    for m in LIST_RE.finditer(body):
        if m.group(1) == 'begin':
            depth += 1
        elif m.group(1) == 'end':
            depth = max(0, depth - 1)
        elif depth == 0:
            if cur is not None:
                items.append(body[cur:m.start()])
            cur = m.end()
    if cur is not None:
        items.append(body[cur:])
    return [i for i in items if i.strip()]

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


def parse_version(vdir, arxiv_id, version, cite_map=None):
    """Return (elements, hierarchy) rows for one version directory.

    cite_map maps this version's original citation keys to canonical keys; citations are
    rewritten before IDs are computed so content citing the same work dedups across versions.
    """
    main = find_main_tex(vdir)
    if main is None:  # PDF-only version
        return [], []
    body = extract_body(expand_inputs(main, main.parent))
    body = canonical_cites(BIB_RE.sub('\n\n', body), cite_map)
    elements, hierarchy = {}, []

    def add(kind, content, parent):
        eid = make_id(arxiv_id, kind, content)
        elements[eid] = (eid, arxiv_id, kind, content)
        hierarchy.append((arxiv_id, version, eid, parent))
        return eid

    def pull_math(m):
        return '\n\n\x02' + normalize_math(next(g for g in m.groups()[2:] if g is not None)) + '\x02\n\n'

    def add_text(text, parent):
        def pull_float(m):
            add(m.group(1), m.group(0).strip(), parent)
            return '\n\n'
        text = FLOAT_RE.sub(pull_float, text)
        text, lists = split_lists(text)
        for lst in lists:
            items = split_items(lst)
            list_id = add('itemize', '\n'.join(clean_text(i) for i in items), parent)
            for item in items:
                add_text(item, add('item', clean_text(item), list_id))
        # Formulas become placeholders so their position splits paragraphs like in the PDF.
        parts = re.split(r'\x02(.*?)\x02', MATH_RE.sub(pull_math, text), flags=re.S)
        for formula in parts[1::2]:
            add('equation', formula, parent)
        for para in re.split(r'\n\s*\n', '\n\n'.join(parts[0::2])):
            for s in split_sentences(clean_text(para)):
                if is_prose(s):
                    add('sentence', s, parent)

    root = add('document', arxiv_id, arxiv_id)
    stack = [(0, root)]
    pieces = SEC_RE.split(body)
    add_text(pieces[0], root)
    skip_below = None  # level of a References/Bibliography heading being skipped
    for i in range(1, len(pieces), 3):
        cmd, title, text = pieces[i:i + 3]
        level = LEVEL[cmd]
        if skip_below is not None and level > skip_below:
            continue
        skip_below = level if clean_text(title).strip().lower() in BIB_TITLES else None
        if skip_below is not None:
            continue
        while stack[-1][0] >= level:
            stack.pop()
        sid = add(cmd, clean_text(title), stack[-1][1])
        stack.append((level, sid))
        add_text(text, sid)
    return list(elements.values()), hierarchy
