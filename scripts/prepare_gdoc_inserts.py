#!/usr/bin/env python3
"""Transform a local summary + raw transcript into gdoc-ready insert files.

Produces:
  - /tmp/gdoc-summary.txt          (summary with heading block rewritten, --- lines stripped,
                                    blank lines collapsed between ## headings and bodies)
  - /tmp/gdoc-raw-transcript.txt   (raw transcript with `# YYYY-MM-DD` prepended and
                                    **Me**:/**Other**: substituted for confirmed first names)

Fails loudly (non-zero exit + stderr) on any unexpected input shape.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
H1_DATE_RE = re.compile(r"^# \d{4}-\d{2}-\d{2}\s*$")


def die(msg: str) -> None:
    print(f"prepare_gdoc_inserts: {msg}", file=sys.stderr)
    sys.exit(1)


def transform_summary(src: str, date: str) -> str:
    lines = src.splitlines()

    # Find the Meeting summary heading block. Must start with `# Meeting summary:`.
    if not lines or not lines[0].startswith("# Meeting summary:"):
        die(f"summary first line must start with '# Meeting summary:', got: {lines[0] if lines else '<empty>'!r}")

    # Skip the heading block: `# Meeting summary: ...`, blank, `**Date:** ...`, blank,
    # `**Participants:** ...`, then optional `---` and blank. We swallow everything up to
    # and including the first `---` line after the participants, if present.
    i = 1
    saw_participants = False
    while i < len(lines):
        line = lines[i]
        if line.startswith("**Participants:**"):
            saw_participants = True
            i += 1
            continue
        if saw_participants and line.strip() == "---":
            i += 1
            # also swallow one following blank line if present
            if i < len(lines) and lines[i].strip() == "":
                i += 1
            break
        if saw_participants and line.strip() != "" and not line.startswith("**"):
            # participants line was the last of the block, no --- separator; stop here
            break
        i += 1
    else:
        die("failed to locate end of summary heading block (no `## Summary` reached)")

    body_lines = lines[i:]

    # Strip all `---` horizontal rule lines.
    body_lines = [ln for ln in body_lines if ln.strip() != "---"]

    # Rebuild with collapsed blank lines.
    out: list[str] = [f"# {date}"]

    # Walk body, dropping:
    #  - leading blanks (between # heading and first ## section)
    #  - blank lines immediately after a `##` heading (so body abuts heading)
    #  - runs of >1 blank line (collapse to 1)
    j = 0
    while j < len(body_lines) and body_lines[j].strip() == "":
        j += 1

    prev_blank = False
    prev_was_h2 = False
    for ln in body_lines[j:]:
        if ln.strip() == "":
            # skip blank right after an h2
            if prev_was_h2:
                continue
            # collapse consecutive blanks
            if prev_blank:
                continue
            # Ensure there IS a blank line before the NEXT h2 — we'll emit this blank; the
            # next-iteration h2 will keep it. If the next non-blank is plain text, we
            # still keep a single blank. So just emit.
            out.append("")
            prev_blank = True
            prev_was_h2 = False
            continue

        if ln.startswith("## "):
            # ensure a blank line separator before a new h2 (unless we're right after the
            # date heading, which is the first output line)
            if out and out[-1] != "" and not (len(out) == 1 and H1_DATE_RE.match(out[0])):
                out.append("")
            # If after date heading and no blank yet, do NOT insert one (no blank between
            # # date and first ## Summary). This matches the original rule: no blank
            # between `# YYYY-MM-DD` and the first `## Summary`.
            out.append(ln)
            prev_blank = False
            prev_was_h2 = True
            continue

        out.append(ln)
        prev_blank = False
        prev_was_h2 = False

    # Drop trailing blank lines.
    while out and out[-1] == "":
        out.pop()

    return "\n".join(out) + "\n"


def transform_raw_transcript(src: str, date: str, user_first: str, other_first: str) -> str:
    # Substitute speaker labels. `**Me**:` → `**{user_first}**:`
    out = src.replace("**Me**:", f"**{user_first}**:").replace("**Other**:", f"**{other_first}**:")

    # Strip the Granola preamble if present. Pattern (verified from data/transcripts/):
    #   `# <Title>\nDate: YYYY-MM-DD\n` optionally followed by blank lines.
    # If matched, drop those two lines. Otherwise leave body untouched.
    lines = out.splitlines()
    if len(lines) >= 2 and lines[0].startswith("# ") and lines[1].startswith("Date:"):
        lines = lines[2:]
        while lines and lines[0].strip() == "":
            lines = lines[1:]
        out = "\n".join(lines)

    body = out.lstrip("\n")
    if not body.endswith("\n"):
        body += "\n"
    return f"# {date}\n\n{body}"


def validate_summary(out: str) -> None:
    lines = out.splitlines()
    if not lines:
        die("summary output is empty")
    if not H1_DATE_RE.match(lines[0]):
        die(f"summary first line must be '# YYYY-MM-DD', got: {lines[0]!r}")
    if any(ln.strip() == "---" for ln in lines):
        die("summary output still contains '---' lines after transform")
    # No two consecutive blank lines.
    for a, b in zip(lines, lines[1:]):
        if a == "" and b == "":
            die("summary output contains consecutive blank lines")


def validate_raw_transcript(out: str) -> None:
    lines = out.splitlines()
    if not lines:
        die("raw transcript output is empty")
    if not H1_DATE_RE.match(lines[0]):
        die(f"raw transcript first line must be '# YYYY-MM-DD', got: {lines[0]!r}")
    if "**Me**:" in out or "**Other**:" in out:
        die("raw transcript still contains **Me**: or **Other**: after substitution")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True, type=Path, help="Path to summary markdown file")
    ap.add_argument("--transcript", required=True, type=Path, help="Path to raw transcript markdown file")
    ap.add_argument("--user-first", required=True, help="User's first name (replaces **Me**:)")
    ap.add_argument("--other-first", required=True, help="Other participant's first name (replaces **Other**:)")
    ap.add_argument("--date", required=True, help="Call date as YYYY-MM-DD")
    ap.add_argument("--out-summary", default="/tmp/gdoc-summary.txt", type=Path)
    ap.add_argument("--out-transcript", default="/tmp/gdoc-raw-transcript.txt", type=Path)
    args = ap.parse_args()

    if not DATE_RE.match(args.date):
        die(f"--date must be YYYY-MM-DD, got: {args.date!r}")
    if not args.summary.exists():
        die(f"summary file not found: {args.summary}")
    if not args.transcript.exists():
        die(f"transcript file not found: {args.transcript}")
    if not args.user_first.strip() or not args.other_first.strip():
        die("--user-first and --other-first must be non-empty")

    summary_out = transform_summary(args.summary.read_text(encoding="utf-8"), args.date)
    validate_summary(summary_out)
    args.out_summary.write_text(summary_out, encoding="utf-8")

    transcript_out = transform_raw_transcript(
        args.transcript.read_text(encoding="utf-8"),
        args.date,
        args.user_first.strip(),
        args.other_first.strip(),
    )
    validate_raw_transcript(transcript_out)
    args.out_transcript.write_text(transcript_out, encoding="utf-8")

    print(f"OK summary -> {args.out_summary}")
    print(f"OK transcript -> {args.out_transcript}")


if __name__ == "__main__":
    main()
