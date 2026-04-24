#!/usr/bin/env python3
"""Resolve the meeting doc ID for a person.

Lookup order:
  1. people.json registry — if `people[<key>].meeting_doc.url` is set, extract doc_id.
  2. Fallback: `gdoc find "ph-<initials>" --title` — if exactly one hit, cache it back
     into people.json under the person's entry and return it.
  3. Not found — return {"source": "not_found"} and exit 0 (caller decides what to do).

Output: single-line JSON on stdout:
  {"doc_id": "<id>|null", "source": "registry|search|not_found", "person_key": "<key>"}

Fails loudly (non-zero exit + stderr) on:
  - Invalid registry JSON
  - Ambiguous gdoc search (>1 match)
  - gdoc CLI error
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


REGISTRY_PATH = Path.home() / ".agents" / "data" / "people.json"
DOC_ID_RE = re.compile(r"/document/d/([A-Za-z0-9_-]+)")


def die(msg: str) -> None:
    print(f"find_meeting_doc: {msg}", file=sys.stderr)
    sys.exit(1)


def slugify(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip().lower())


def extract_doc_id(url: str) -> str | None:
    m = DOC_ID_RE.search(url)
    return m.group(1) if m else None


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        die(f"registry not found: {REGISTRY_PATH}")
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"registry JSON invalid: {e}")


def save_registry(data: dict) -> None:
    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def search_gdoc(initials: str) -> str | None:
    """Run `gdoc find "ph-{initials}" --title --json`. Return doc URL or None."""
    if not shutil.which("gdoc"):
        die("gdoc CLI not found in PATH")
    query = f"ph-{initials}"
    try:
        res = subprocess.run(
            ["gdoc", "find", query, "--title", "--json"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        die(f"gdoc find '{query}' timed out")
    if res.returncode != 0:
        die(f"gdoc find '{query}' failed: {res.stderr.strip()}")
    try:
        payload = json.loads(res.stdout)
    except json.JSONDecodeError:
        die(f"gdoc find returned non-JSON: {res.stdout[:200]!r}")
    # Shape: {"ok": true, "files": [{"id": "...", "name": "...", "url": "..."}, ...]}
    files = payload.get("files") or []
    if len(files) == 0:
        return None
    if len(files) > 1:
        names = [f.get("name", "?") for f in files]
        die(f"ambiguous gdoc search for '{query}': {len(files)} matches: {names}")
    f = files[0]
    return f.get("url") or (f"https://docs.google.com/document/d/{f['id']}/edit" if "id" in f else None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="Full name (e.g., 'Jane Smith')")
    ap.add_argument("--initials", help="Lowercase initials for gdoc search fallback (e.g., 'al'). "
                                        "Required if person not in registry.")
    args = ap.parse_args()

    key = slugify(args.name)
    data = load_registry()
    people = data.setdefault("people", {})
    entry = people.get(key)

    # 1) Registry lookup
    if entry and entry.get("meeting_doc") and entry["meeting_doc"].get("url"):
        doc_id = extract_doc_id(entry["meeting_doc"]["url"])
        if not doc_id:
            die(f"registry entry for '{key}' has meeting_doc.url but no parseable doc ID")
        print(json.dumps({"doc_id": doc_id, "source": "registry", "person_key": key}))
        return

    # 2) Search fallback
    initials = (args.initials or (entry.get("initials") if entry else None) or "").strip().lower()
    if not initials:
        die(f"person '{key}' not in registry and no --initials provided; cannot search")

    url = search_gdoc(initials)
    if not url:
        print(json.dumps({"doc_id": None, "source": "not_found", "person_key": key}))
        return

    doc_id = extract_doc_id(url)
    if not doc_id:
        die(f"gdoc search returned URL with no parseable doc ID: {url}")

    # Cache back into registry
    if not entry:
        entry = {"full_name": args.name, "initials": initials}
        people[key] = entry
    entry["meeting_doc"] = {
        "url": url,
        "title": f"ph-{initials} meeting doc (auto-cached)",
        "cached_at": dt.date.today().isoformat(),
    }
    save_registry(data)

    print(json.dumps({"doc_id": doc_id, "source": "search", "person_key": key}))


if __name__ == "__main__":
    main()
