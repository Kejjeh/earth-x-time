"""The knowledge-time bounds, read from the one place that defines them.

src/20_core.js says, next to the constant:

    The upper end of knowledge-time is NOW, not a constant someone typed once.
    ... Move this when the record moves past it.

It was moved, from 2025 to 2026, so that a 2026 paper's status entry could fire.
Two of the four copies were not moved with it, and each failed differently:
tools/stage4_merge.py refused a well-formed 2026 claim outright, and
tools/ingest.py silently rewrote a 2026 citation's year to 2025 - a sourced
claim with the wrong source, in the tool whose entire job is provenance.

So nothing mirrors the constant by hand any more. This reads it out of the
source file, and fails loudly rather than falling back to a guess: a wrong
ceiling that still runs is how this went unnoticed in the first place.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, "src", "20_core.js")

_DECL = re.compile(r"const\s+KT_MIN\s*=\s*(\d{3,4})\s*,\s*KT_MAX\s*=\s*(\d{3,4})\s*;")


def read_bounds(path=CORE):
    """(KT_MIN, KT_MAX) as src/20_core.js declares them."""
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except OSError as e:
        raise SystemExit(f"FATAL: cannot read the knowledge-time bounds from {path}: {e}")
    m = _DECL.search(src)
    if not m:
        raise SystemExit(
            f"FATAL: no `const KT_MIN = ..., KT_MAX = ...;` in {path}. "
            "The Python tools read the bounds from there rather than mirroring "
            "them; if the declaration moved or changed shape, update "
            "tools/knowledge_time.py to match rather than re-typing the numbers.")
    lo, hi = int(m.group(1)), int(m.group(2))
    if not (1000 <= lo < hi <= 2200):
        raise SystemExit(f"FATAL: implausible knowledge-time bounds in {path}: {lo}..{hi}")
    return lo, hi


KT_MIN, KT_MAX = read_bounds()
