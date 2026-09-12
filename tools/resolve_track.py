#!/usr/bin/env python3
"""
resolve_track.py — print Resume_Master.tex with `\\ifcase\\ResumeType` resolved to one
one-page track (0-5) and the two-page-only blocks removed.

The customiser's DEPTH gate diffs a tailored output against THIS, not against the raw
master: a raw diff always shows Skills churn (the \\ifcase block disappears), so it could
never fail. Usage:

    python3 tools/resolve_track.py 4 > /tmp/base4.tex
    diff /tmp/base4.tex Job_Applications_Resumes/<today>/src/resume_X.tex
"""
import re
import sys
from pathlib import Path

MASTER = Path(__file__).resolve().parent.parent / "Resume" / "Final_Resumes" / "Resume_Master.tex"


def resolve(master: str, track: int) -> str:
    m = re.search(r"\\ifcase\\ResumeType\n(.*?)\\fi\n", master, re.S)
    if not m:
        return master
    cases = m.group(1).split("\\or\n")
    if not 0 <= track < len(cases):
        raise SystemExit(f"track must be 0..{len(cases) - 1}")
    tex = master[:m.start()] + cases[track] + master[m.end():]
    tex = tex.replace("\\newif\\ifTwoPage\n\\ifnum\\ResumeType=6 \\TwoPagetrue \\else \\TwoPagefalse \\fi\n", "")
    tex = tex.replace("\\ifTwoPage\\newpage\\fi\n", "")
    return re.sub(r"\\ifTwoPage\n.*?\\fi\n", "", tex, flags=re.S)


def self_test() -> None:
    src = ("head\n\\newif\\ifTwoPage\n\\ifnum\\ResumeType=6 \\TwoPagetrue \\else \\TwoPagefalse \\fi\n"
           "\\ifcase\\ResumeType\nA\n\\or\nB\n\\or\nC\n\\fi\n"
           "mid\n\\ifTwoPage\\newpage\\fi\n\\ifTwoPage\nTWO\n\\fi\ntail\n")
    assert resolve(src, 0) == "head\nA\nmid\ntail\n"
    assert resolve(src, 2) == "head\nC\nmid\ntail\n"
    assert "TWO" not in resolve(src, 1) and "\\ifcase" not in resolve(src, 1)
    assert resolve("no cases here\n", 0) == "no cases here\n"
    print("OK  resolve_track self-check passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
        sys.exit(0)
    track = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    sys.stdout.write(resolve(MASTER.read_text(encoding="utf-8"), track))
