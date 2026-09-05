#!/usr/bin/env python3
"""
Granola transcript extraction utility.

Uses Granola's official public API (https://public-api.granola.ai/v1),
authenticated with a personal API key. Generate a key once in the Granola
desktop app: Settings -> Connectors -> API keys -> Create new key (requires a
Business-plan workspace; keys look like `grn_...`). Store it in either:

    ~/.config/granola-summarise/api-key   (a single line; chmod 600)

or the GRANOLA_API_KEY environment variable (which takes precedence).

Usage:
    python granola.py check             # Check for recent call or list 5 most recent
    python granola.py list              # List recent meetings with transcripts
    python granola.py get <note_id>     # Get transcript for a specific meeting
    python granola.py recent [n]        # Get transcript for nth most recent meeting (default: 1)

Transcripts are automatically saved to the data/transcripts/ folder.

Note: the official API only returns notes that already have a generated AI
summary AND transcript. A call that just ended may not appear (or may 404 on
`get`) until Granola finishes processing it — wait a minute and retry.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://public-api.granola.ai/v1"

# Where the personal API key lives. Env var wins; otherwise this file (kept
# OUTSIDE the skill's git repo so the key is never committed/pushed).
API_KEY_ENV = "GRANOLA_API_KEY"
API_KEY_FILE = Path.home() / ".config" / "granola-summarise" / "api-key"

SKILL_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = SKILL_DIR / "data" / "transcripts"
SUMMARIES_DIR = SKILL_DIR / "data" / "summaries"

# How recent a call must be to auto-summarise (in minutes)
RECENT_THRESHOLD_MINUTES = 30

# Longest plausible meeting. Used to sanity-check auto mode: a note whose
# meeting started longer ago than this is not "the call that just ended", even
# if its updated_at was bumped moments ago.
MAX_MEETING_HOURS = 4

# Max page size the API allows for GET /notes
MAX_PAGE_SIZE = 30


def _die(msg: str) -> "None":
    """Print an error to stderr and exit non-zero."""
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def get_api_key() -> str:
    """Return the Granola API key from the env var or the config file.

    Fails loudly with setup instructions if neither is present. This is a hard
    failure by design — the old code silently fell back to a stale token, which
    masked auth problems as confusing 'Unauthorized' errors downstream."""
    key = os.environ.get(API_KEY_ENV, "").strip()
    source = API_KEY_ENV
    if not key and API_KEY_FILE.exists():
        try:
            key = API_KEY_FILE.read_text().strip()
            source = str(API_KEY_FILE)
        except OSError as e:
            _die(f"Could not read {API_KEY_FILE}: {e}")
    if not key:
        _die(
            "No Granola API key found. Set one up once:\n"
            "  1. Granola desktop app -> Settings -> Connectors -> API keys -> Create new key\n"
            "     (requires a Business-plan workspace; the key looks like grn_...)\n"
            f"  2. Save it to {API_KEY_FILE} (chmod 600), e.g.:\n"
            f"       mkdir -p {API_KEY_FILE.parent} \\\n"
            f"         && printf 'grn_XXXX' > {API_KEY_FILE} \\\n"
            f"         && chmod 600 {API_KEY_FILE}\n"
            f"     Or export {API_KEY_ENV}=grn_XXXX"
        )
    if not key.startswith("grn_"):
        print(
            f"Warning: Granola API key from {source} does not start with 'grn_'; "
            "the API may reject it.",
            file=sys.stderr,
        )
    return key


def api_get(path: str, params: dict | None = None) -> object:
    """GET a Granola public-API endpoint and return parsed JSON.

    Raises loud, actionable errors for the common failure modes (missing/invalid
    key, unprocessed note, rate limiting) rather than returning None."""
    key = get_api_key()
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read()[:300].decode("utf-8", "replace")
        except Exception:
            pass
        if e.code == 401:
            _die(
                "Granola API rejected the key (401 Unauthorized). Generate a new "
                "key in Granola (Settings -> Connectors -> API keys) and update "
                f"{API_KEY_FILE} or ${API_KEY_ENV}."
            )
        if e.code == 403:
            _die(
                "Granola API returned 403 Forbidden — the key may lack the "
                "required scope (grant it 'Personal notes' or 'Public notes' when "
                "creating the key), or API access is disabled for this workspace."
            )
        if e.code == 404:
            _die(
                f"Granola API 404 for /{path}. The note may not exist, or Granola "
                "hasn't finished generating its AI summary + transcript yet "
                "(only processed notes are returned). Wait a minute and retry."
            )
        if e.code == 429:
            _die("Granola API rate limit hit (429). Wait a few seconds and retry.")
        _die(f"Granola API error {e.code} for /{path}: {body}")
    except urllib.error.URLError as e:
        _die(f"Could not reach the Granola API ({API_BASE}): {e.reason}")


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.replace('&', 'and')
    text = re.sub(r'[^a-z0-9]+', '-', text.lower())
    text = text.strip('-')
    return text[:50]


def parse_iso_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    ts = ts.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _meeting_timestamp(doc: dict) -> str:
    """Return when the meeting itself happened.

    Do NOT use ``updated_at`` for this. Granola bumps a note's ``updated_at``
    when the *next* note is created, so it lags one meeting behind: the 17 Aug
    call carried an 18 Aug ``updated_at``. Using it dated every row in the
    selection list to the *following* call's date.

    ``calendar_event.scheduled_start_time`` is the truth when present (the list
    endpoint often omits it); ``created_at`` is the note's own creation, which
    tracks the meeting start closely. ``updated_at`` is a last resort only."""
    cal = doc.get('calendar_event') or {}
    return (
        cal.get('scheduled_start_time')
        or doc.get('created_at')
        or doc.get('updated_at')
        or ''
    )


def _activity_timestamp(doc: dict) -> str:
    """Return the note's most recent activity (processing/edit) timestamp.

    For the newest note this approximates when Granola finished processing the
    call, i.e. shortly after it ended — useful for "did a call just finish?".
    It is unreliable for older notes (see ``_meeting_timestamp``), so only use
    it on the most recent note and always cross-check the meeting start."""
    return doc.get('updated_at') or doc.get('created_at') or ''


def get_recent_documents(limit: int = 5) -> list[dict]:
    """Fetch recent notes from the Granola API, most-recent meeting first.

    Pulls one max-size page (30) and re-sorts by meeting time; that's ample for
    the 'most recent N' use case without paginating the whole account."""
    resp = api_get("notes", {"page_size": MAX_PAGE_SIZE})
    if not isinstance(resp, dict) or "notes" not in resp:
        _die(f"Unexpected API response for list notes: {str(resp)[:200]}")
    notes = resp["notes"]
    if not isinstance(notes, list):
        _die("Unexpected API response: 'notes' is not a list")
    notes.sort(key=_meeting_timestamp, reverse=True)
    return notes[:limit]


def check_recent():
    """
    Check if there's a recent call (within RECENT_THRESHOLD_MINUTES).

    If yes, output JSON indicating auto-summarise mode.
    If no, output a numbered list of the 5 most recent calls for selection.
    """
    docs = get_recent_documents(limit=5)

    if not docs:
        print("No meetings found.")
        return

    # Auto mode needs two things to agree, because neither timestamp is
    # trustworthy alone:
    #   1. activity (processing finished) within RECENT_THRESHOLD_MINUTES, and
    #   2. the meeting itself started within MAX_MEETING_HOURS.
    # Check (2) is what stops the classic misfire: starting a new call bumps the
    # *previous* note's updated_at to now while the new note is still
    # processing and therefore invisible, so check (1) alone would auto-select
    # yesterday's meeting.
    most_recent = docs[0]
    activity_ts = _activity_timestamp(most_recent)
    meeting_ts = _meeting_timestamp(most_recent)

    if activity_ts and meeting_ts:
        now = datetime.now(timezone.utc)
        minutes_ago = (now - parse_iso_timestamp(activity_ts)).total_seconds() / 60
        meeting_hours_ago = (
            now - parse_iso_timestamp(meeting_ts)
        ).total_seconds() / 3600

        if (
            minutes_ago <= RECENT_THRESHOLD_MINUTES
            and meeting_hours_ago <= MAX_MEETING_HOURS
        ):
            result = {
                'mode': 'auto',
                'id': most_recent['id'],
                'title': most_recent.get('title') or 'Untitled',
                'minutes_ago': round(minutes_ago, 1),
                'date': meeting_ts[:10],
            }
            print(json.dumps(result))
            return

    # No recent call - show selection list
    result = {
        'mode': 'select',
        'meetings': [],
    }

    for i, doc in enumerate(docs, 1):
        meeting_ts = _meeting_timestamp(doc)
        date_str = meeting_ts[:10] if meeting_ts else 'Unknown'
        result['meetings'].append({
            'number': i,
            'id': doc['id'],
            'title': doc.get('title') or 'Untitled',
            'date': date_str,
        })

    print(json.dumps(result))


def list_meetings():
    """List recent meetings."""
    docs = get_recent_documents(limit=20)

    print(f"Found {len(docs)} recent meeting(s):\n")
    for i, doc in enumerate(docs, 1):
        meeting_ts = _meeting_timestamp(doc)
        date_str = meeting_ts[:10] if meeting_ts else 'Unknown date'
        print(f"{i}. [{date_str}] {doc.get('title') or 'Untitled'}")
        print(f"   ID: {doc['id']}")
        print()


def _transcript_date(note: dict) -> str:
    """Best date (YYYY-MM-DD) for a note: scheduled start, else created."""
    ts = _meeting_timestamp(note)
    return ts[:10] if ts else 'unknown-date'


def build_transcript(note_id: str) -> tuple[str, str, str]:
    """
    Fetch and build transcript markdown for a specific note.

    Returns:
        tuple: (markdown_content, title, date_str)
    """
    note = api_get(f"notes/{note_id}", {"include": "transcript"})
    if not isinstance(note, dict):
        _die(f"Unexpected API response for note {note_id}: {str(note)[:200]}")

    title = note.get('title') or 'Untitled'
    date_str = _transcript_date(note)

    chunks = note.get('transcript')
    if not isinstance(chunks, list) or len(chunks) == 0:
        _die(
            f"No transcript found for note {note_id}. The note may still be "
            "processing, or was never transcribed."
        )

    # Sort by start time so speaker turns are in order.
    chunks.sort(key=lambda c: c.get('start_time') or '')

    lines = []
    lines.append(f"# {title}")
    lines.append(f"Date: {date_str}")
    lines.append("")

    # Group consecutive segments by speaker. The downstream gdoc/email steps
    # rely on the "Me"/"Other" labels (they get substituted for real names), so
    # keep those exact labels: microphone == the person running Granola ("Me"),
    # any other source == "Other".
    current_speaker = None
    current_text = []

    for chunk in chunks:
        speaker = chunk.get('speaker') or {}
        source = speaker.get('source', 'unknown')
        text = (chunk.get('text') or '').strip()

        if not text:
            continue

        label = 'Me' if source == 'microphone' else 'Other'

        if label != current_speaker:
            if current_text:
                lines.append(f"**{current_speaker}**: {' '.join(current_text)}")
                lines.append("")
            current_speaker = label
            current_text = [text]
        else:
            current_text.append(text)

    if current_text:
        lines.append(f"**{current_speaker}**: {' '.join(current_text)}")

    return '\n'.join(lines), title, date_str


def get_transcript(note_id: str):
    """Get and save the full transcript for a specific note."""
    markdown, title, date_str = build_transcript(note_id)

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{date_str}-{slugify(title or 'untitled')}.md"
    filepath = TRANSCRIPTS_DIR / filename

    with open(filepath, 'w') as f:
        f.write(markdown)

    print(markdown)
    print(f"\n---\nTranscript saved to: {filepath}", file=sys.stderr)


def get_recent_transcript(n: int = 1):
    """Get transcript for the nth most recent meeting."""
    docs = get_recent_documents(limit=max(n, 5))

    if n < 1 or n > len(docs):
        _die(f"Only {len(docs)} meeting(s) available")

    note_id = docs[n - 1]['id']
    get_transcript(note_id)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'check':
        check_recent()
    elif command == 'list':
        list_meetings()
    elif command == 'get':
        if len(sys.argv) < 3:
            _die("Note ID required")
        get_transcript(sys.argv[2])
    elif command == 'recent':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        get_recent_transcript(n)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
