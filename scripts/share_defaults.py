#!/usr/bin/env python3
"""
Per-person sharing defaults for the summarise-granola skill.

Reads/writes people[<key>].share_defaults in the people registry
(~/.agents/data/people.json), so the Step 2.6 sharing/comment/approval choices
can be remembered per person and reused on later calls.

Usage:
    share_defaults.py get <person_key>       # print the saved defaults as JSON ({} if none)
    share_defaults.py summary <person_key>   # print a one-line human label ('' if none)
    share_defaults.py set <person_key> \
        --sharing meeting_doc,slack_dm --comment no_comment --approval auto_send

Person key = lowercase, hyphenated full name (e.g. "Jane Smith" -> "jane-smith").

Canonical tokens:
    sharing  : any of  meeting_doc, email, slack_dm, tidied_transcript  (comma-separated; may be empty)
    comment  : no_comment | add_comment
    approval : auto_send | preview
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REGISTRY = Path.home() / ".agents" / "data" / "people.json"

SHARING_TOKENS = {"meeting_doc", "email", "slack_dm", "tidied_transcript"}
COMMENT_TOKENS = {"no_comment", "add_comment"}
APPROVAL_TOKENS = {"auto_send", "preview"}

SHARING_LABELS = {
    "meeting_doc": "doc",
    "email": "email",
    "slack_dm": "Slack DM",
    "tidied_transcript": "tidied transcript",
}
COMMENT_LABELS = {"no_comment": "no comment", "add_comment": "with comment"}
APPROVAL_LABELS = {"auto_send": "auto-send", "preview": "preview first"}


def _load() -> dict:
    if not REGISTRY.exists():
        return {"people": {}}
    return json.loads(REGISTRY.read_text())


def _save(data: dict) -> None:
    # 2-space indent, no trailing newline — matches the existing file style, so
    # writing back changes only the entry we touched.
    REGISTRY.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _defaults_for(data: dict, key: str) -> dict:
    return (data.get("people", {}).get(key, {}) or {}).get("share_defaults", {}) or {}


def _summary(sd: dict) -> str:
    if not sd:
        return ""
    parts = [SHARING_LABELS.get(s, s) for s in sd.get("sharing", [])]
    channels = " + ".join(parts) if parts else "no sharing"
    comment = COMMENT_LABELS.get(sd.get("comment", ""), sd.get("comment", ""))
    approval = APPROVAL_LABELS.get(sd.get("approval", ""), sd.get("approval", ""))
    bits = [channels]
    if comment:
        bits.append(comment)
    if approval:
        bits.append(approval)
    return " · ".join(bits)


def cmd_get(args):
    print(json.dumps(_defaults_for(_load(), args.person_key)))


def cmd_summary(args):
    print(_summary(_defaults_for(_load(), args.person_key)))


def cmd_set(args):
    sharing = [t.strip() for t in args.sharing.split(",") if t.strip()] if args.sharing else []
    bad = set(sharing) - SHARING_TOKENS
    if bad:
        sys.exit(f"Error: unknown sharing token(s): {', '.join(sorted(bad))}")
    if args.comment not in COMMENT_TOKENS:
        sys.exit(f"Error: --comment must be one of {sorted(COMMENT_TOKENS)}")
    if args.approval not in APPROVAL_TOKENS:
        sys.exit(f"Error: --approval must be one of {sorted(APPROVAL_TOKENS)}")

    data = _load()
    people = data.setdefault("people", {})
    entry = people.setdefault(args.person_key, {})
    entry["share_defaults"] = {
        "sharing": sharing,
        "comment": args.comment,
        "approval": args.approval,
        "updated_at": date.today().isoformat(),
    }
    _save(data)
    print(f"saved share_defaults for {args.person_key}: {_summary(entry['share_defaults'])}")


def main():
    p = argparse.ArgumentParser(description="Per-person sharing defaults")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get")
    g.add_argument("person_key")
    g.set_defaults(func=cmd_get)

    s = sub.add_parser("summary")
    s.add_argument("person_key")
    s.set_defaults(func=cmd_summary)

    st = sub.add_parser("set")
    st.add_argument("person_key")
    st.add_argument("--sharing", default="", help="comma-separated sharing tokens (may be empty)")
    st.add_argument("--comment", required=True)
    st.add_argument("--approval", required=True)
    st.set_defaults(func=cmd_set)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
