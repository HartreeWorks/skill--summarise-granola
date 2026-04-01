#!/usr/bin/env python3
"""
Granola transcript extraction utility.

Usage:
    python granola.py check             # Check for recent call or list 5 most recent
    python granola.py list              # List all meetings with transcripts
    python granola.py get <doc_id>      # Get transcript for a specific meeting
    python granola.py recent [n]        # Get transcript for nth most recent meeting (default: 1)

Transcripts are automatically saved to the data/transcripts/ folder.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SUPABASE_AUTH = Path.home() / "Library" / "Application Support" / "Granola" / "supabase.json"
API_BASE = "https://api.granola.ai/v1"
SKILL_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = SKILL_DIR / "data" / "transcripts"
SUMMARIES_DIR = SKILL_DIR / "data" / "summaries"

# How recent a call must be to auto-summarise (in minutes)
RECENT_THRESHOLD_MINUTES = 30


def get_access_token() -> str:
    """Read the Granola access token from the local auth file."""
    if not SUPABASE_AUTH.exists():
        print(f"Error: Granola auth not found at {SUPABASE_AUTH}", file=sys.stderr)
        print("Is Granola installed and signed in?", file=sys.stderr)
        sys.exit(1)

    with open(SUPABASE_AUTH, 'r') as f:
        data = json.load(f)

    tokens = json.loads(data['workos_tokens'])
    return tokens['access_token']


def api_call(endpoint: str, payload: dict) -> any:
    """Make an authenticated POST request to the Granola API."""
    token = get_access_token()

    result = subprocess.run(
        [
            'curl', '-s', '--compressed', '-X', 'POST',
            f'{API_BASE}/{endpoint}',
            '-H', f'Authorization: Bearer {token}',
            '-H', 'Content-Type: application/json',
            '-d', json.dumps(payload),
        ],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        print(f"Error: API call failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON response: {result.stdout[:200]}", file=sys.stderr)
        sys.exit(1)


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


def get_recent_documents(limit: int = 5) -> list[dict]:
    """Fetch recent documents from the Granola API."""
    docs = api_call('get-documents', {'limit': limit})
    if not isinstance(docs, list):
        print(f"Error: Unexpected API response format", file=sys.stderr)
        sys.exit(1)
    return docs


def check_recent():
    """
    Check if there's a recent call (within 30 minutes).

    If yes, output JSON indicating auto-summarise mode.
    If no, output a numbered list of the 5 most recent calls for selection.
    """
    docs = get_recent_documents(limit=5)

    if not docs:
        print("No meetings found.")
        return

    # Check if most recent meeting was created within threshold
    most_recent = docs[0]
    created_at = most_recent.get('created_at')

    if created_at:
        meeting_time = parse_iso_timestamp(created_at)
        now = datetime.now(timezone.utc)
        minutes_ago = (now - meeting_time).total_seconds() / 60

        if minutes_ago <= RECENT_THRESHOLD_MINUTES:
            result = {
                'mode': 'auto',
                'id': most_recent['id'],
                'title': most_recent.get('title', 'Untitled'),
                'minutes_ago': round(minutes_ago, 1),
            }
            print(json.dumps(result))
            return

    # No recent call - show selection list
    result = {
        'mode': 'select',
        'meetings': [],
    }

    for i, doc in enumerate(docs, 1):
        date_str = doc['created_at'][:10] if doc.get('created_at') else 'Unknown'
        result['meetings'].append({
            'number': i,
            'id': doc['id'],
            'title': doc.get('title', 'Untitled'),
            'date': date_str,
        })

    print(json.dumps(result))


def list_meetings():
    """List recent meetings."""
    docs = get_recent_documents(limit=20)

    print(f"Found {len(docs)} recent meeting(s):\n")
    for i, doc in enumerate(docs, 1):
        date_str = doc['created_at'][:10] if doc.get('created_at') else 'Unknown date'
        print(f"{i}. [{date_str}] {doc.get('title', 'Untitled')}")
        print(f"   ID: {doc['id']}")
        print()


def build_transcript(doc_id: str) -> tuple[str, str, str]:
    """
    Fetch and build transcript markdown for a specific document.

    Returns:
        tuple: (markdown_content, title, date_str)
    """
    # Fetch document metadata
    docs_response = api_call('get-documents-batch', {'document_ids': [doc_id]})
    if isinstance(docs_response, dict) and 'docs' in docs_response:
        docs_list = docs_response['docs']
    elif isinstance(docs_response, list):
        docs_list = docs_response
    else:
        docs_list = []
    doc = docs_list[0] if docs_list else {}

    title = doc.get('title', 'Untitled')
    created_at = doc.get('created_at', '')
    date_str = created_at[:10] if created_at else 'unknown-date'

    # Fetch transcript chunks
    chunks = api_call('get-document-transcript', {'document_id': doc_id})

    if not isinstance(chunks, list) or len(chunks) == 0:
        print(f"Error: No transcript found for document ID: {doc_id}", file=sys.stderr)
        sys.exit(1)

    # Sort by timestamp
    chunks.sort(key=lambda c: c.get('start_timestamp', ''))

    lines = []
    lines.append(f"# {title}")
    lines.append(f"Date: {date_str}")
    lines.append("")

    # Group consecutive segments by speaker
    current_speaker = None
    current_text = []

    for chunk in chunks:
        source = chunk.get('source', 'unknown')
        text = chunk.get('text', '').strip()

        if not text:
            continue

        speaker = 'Me' if source == 'microphone' else 'Other'

        if speaker != current_speaker:
            if current_text:
                lines.append(f"**{current_speaker}**: {' '.join(current_text)}")
                lines.append("")
            current_speaker = speaker
            current_text = [text]
        else:
            current_text.append(text)

    if current_text:
        lines.append(f"**{current_speaker}**: {' '.join(current_text)}")

    return '\n'.join(lines), title, date_str


def get_transcript(doc_id: str):
    """Get and save the full transcript for a specific document."""
    markdown, title, date_str = build_transcript(doc_id)

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
        print(f"Error: Only {len(docs)} meeting(s) available", file=sys.stderr)
        sys.exit(1)

    doc_id = docs[n - 1]['id']
    get_transcript(doc_id)


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
            print("Error: Document ID required", file=sys.stderr)
            sys.exit(1)
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
