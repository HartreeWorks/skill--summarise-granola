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
import sys
from datetime import datetime, timezone
from pathlib import Path

GRANOLA_CACHE = Path.home() / "Library" / "Application Support" / "Granola" / "cache-v6.json"
SKILL_DIR = Path(__file__).parent.parent
TRANSCRIPTS_DIR = SKILL_DIR / "data" / "transcripts"
SUMMARIES_DIR = SKILL_DIR / "data" / "summaries"

# How recent a call must be to auto-summarise (in minutes)
RECENT_THRESHOLD_MINUTES = 30


def load_granola_data():
    """Load and parse the Granola cache file."""
    if not GRANOLA_CACHE.exists():
        print(f"Error: Granola cache not found at {GRANOLA_CACHE}", file=sys.stderr)
        sys.exit(1)

    with open(GRANOLA_CACHE, 'r') as f:
        data = json.load(f)

    cache = data['cache']
    if isinstance(cache, str):
        cache = json.loads(cache)
    return cache['state']


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    # Replace & with 'and'
    text = text.replace('&', 'and')
    # Convert to lowercase and replace spaces/special chars with hyphens
    text = re.sub(r'[^a-z0-9]+', '-', text.lower())
    # Remove leading/trailing hyphens
    text = text.strip('-')
    return text[:50]  # Limit length


def parse_iso_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    # Handle various ISO formats
    ts = ts.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        # Fallback for edge cases
        return datetime.min.replace(tzinfo=timezone.utc)


def get_meetings_with_transcripts():
    """Get all meetings that have transcripts, sorted by most recent first."""
    state = load_granola_data()
    documents = state['documents']
    transcripts = state['transcripts']

    meetings = []
    for doc_id, transcript in transcripts.items():
        if transcript and len(transcript) > 0:
            if doc_id in documents:
                doc = documents[doc_id]
                meetings.append({
                    'id': doc_id,
                    'title': doc.get('title', 'Untitled'),
                    'created_at': doc.get('created_at'),
                    'updated_at': doc.get('updated_at'),
                    'segment_count': len(transcript)
                })

    # Sort by updated_at (when transcript was last modified), most recent first
    meetings.sort(
        key=lambda x: x['updated_at'] or x['created_at'] or '',
        reverse=True
    )

    return meetings


def check_recent():
    """
    Check if there's a recent call (within 30 minutes).

    If yes, output JSON indicating auto-summarise mode.
    If no, output a numbered list of the 5 most recent calls for selection.
    """
    meetings = get_meetings_with_transcripts()

    if not meetings:
        print("No meetings with transcripts found.")
        return

    # Check if most recent meeting was updated within threshold
    most_recent = meetings[0]
    updated_at = most_recent.get('updated_at') or most_recent.get('created_at')

    if updated_at:
        meeting_time = parse_iso_timestamp(updated_at)
        now = datetime.now(timezone.utc)
        minutes_ago = (now - meeting_time).total_seconds() / 60

        if minutes_ago <= RECENT_THRESHOLD_MINUTES:
            # Recent call found - output JSON for auto-summarise
            result = {
                'mode': 'auto',
                'id': most_recent['id'],
                'title': most_recent['title'],
                'minutes_ago': round(minutes_ago, 1)
            }
            print(json.dumps(result))
            return

    # No recent call - show selection list
    result = {
        'mode': 'select',
        'meetings': []
    }

    # Show up to 5 most recent
    for i, meeting in enumerate(meetings[:5], 1):
        date_str = meeting['created_at'][:10] if meeting['created_at'] else 'Unknown'
        result['meetings'].append({
            'number': i,
            'id': meeting['id'],
            'title': meeting['title'],
            'date': date_str
        })

    print(json.dumps(result))


def list_meetings():
    """List all meetings that have transcripts."""
    meetings = get_meetings_with_transcripts()

    print(f"Found {len(meetings)} meeting(s) with transcripts:\n")
    for i, meeting in enumerate(meetings, 1):
        date_str = meeting['created_at'][:10] if meeting['created_at'] else 'Unknown date'
        print(f"{i}. [{date_str}] {meeting['title']}")
        print(f"   ID: {meeting['id']}")
        print(f"   Segments: {meeting['segment_count']}")
        print()


def build_transcript(doc_id: str) -> tuple[str, str, str]:
    """
    Build transcript markdown for a specific document.

    Returns:
        tuple: (markdown_content, title, date_str)
    """
    state = load_granola_data()
    documents = state['documents']
    transcripts = state['transcripts']

    if doc_id not in transcripts:
        print(f"Error: No transcript found for document ID: {doc_id}", file=sys.stderr)
        sys.exit(1)

    transcript = transcripts[doc_id]
    if not transcript:
        print(f"Error: Transcript is empty for document ID: {doc_id}", file=sys.stderr)
        sys.exit(1)

    # Get document metadata
    doc = documents.get(doc_id, {})
    title = doc.get('title', 'Untitled')
    created_at = doc.get('created_at', '')
    date_str = created_at[:10] if created_at else 'unknown-date'

    lines = []
    lines.append(f"# {title}")
    lines.append(f"Date: {date_str}")
    lines.append("")

    # Group consecutive segments by speaker
    current_speaker = None
    current_text = []

    for segment in transcript:
        source = segment.get('source', 'unknown')
        text = segment.get('text', '').strip()

        if not text:
            continue

        # Map source to speaker label
        speaker = 'Me' if source == 'microphone' else 'Other'

        if speaker != current_speaker:
            # Output previous speaker's text
            if current_text:
                lines.append(f"**{current_speaker}**: {' '.join(current_text)}")
                lines.append("")
            current_speaker = speaker
            current_text = [text]
        else:
            current_text.append(text)

    # Output final speaker's text
    if current_text:
        lines.append(f"**{current_speaker}**: {' '.join(current_text)}")

    return '\n'.join(lines), title, date_str


def get_transcript(doc_id: str):
    """Get and save the full transcript for a specific document."""
    markdown, title, date_str = build_transcript(doc_id)

    # Ensure transcripts directory exists
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # Create filename from date and title
    filename = f"{date_str}-{slugify(title or 'untitled')}.md"
    filepath = TRANSCRIPTS_DIR / filename

    # Save to file
    with open(filepath, 'w') as f:
        f.write(markdown)

    # Print the transcript
    print(markdown)

    # Print save location to stderr so it doesn't mix with content
    print(f"\n---\nTranscript saved to: {filepath}", file=sys.stderr)


def get_recent_transcript(n: int = 1):
    """Get transcript for the nth most recent meeting."""
    meetings = get_meetings_with_transcripts()

    if n < 1 or n > len(meetings):
        print(f"Error: Only {len(meetings)} meeting(s) with transcripts available", file=sys.stderr)
        sys.exit(1)

    doc_id = meetings[n - 1]['id']
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
