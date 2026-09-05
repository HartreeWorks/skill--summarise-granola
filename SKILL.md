---
name: summarise-granola
description: Summarise Granola calls and meeting transcripts.
---

# Granola transcript summarisation

This skill extracts raw meeting transcripts from the Granola app, creates a structured summary, files them to the relevant project, and optionally adds the summary + raw transcript to a shared Google Doc (summary → "Call summaries" tab, raw transcript → "Call transcripts" tab), sends call notes via email, or sends them as a Slack DM. A tidied transcript is opt-in and runs in the background after the main workflow.

**Auto-commit:** Every file this skill saves is committed to git automatically. Files written under `data/` (raw transcripts, summaries, tidied transcripts) live in the `~/.agents` repo and are committed **and pushed** to origin; copies filed into a project folder are committed to that project's local-only repo (commit only, no push — and only when that folder is itself a git repo). This is handled by `scripts/autocommit.sh` at Step 5.5 (main workflow) and Step 8 (tidied transcript). No confirmation is needed — committing this working data is always authorised.

**Update check:** Before starting, run `bash ~/.claude/skills/summarise-granola/scripts/check-update.sh`. If it prints output, show the message and ask the user which action to take:
- **Update now** — run `bash ~/.claude/skills/summarise-granola/scripts/update-skill.sh`, then re-read this SKILL.md before continuing
- **Remind me tomorrow** — run `bash ~/.claude/skills/summarise-granola/scripts/check-update.sh --snooze`, then continue
- **Never ask again** — run `bash ~/.claude/skills/summarise-granola/scripts/check-update.sh --disable`, then continue
If no output, continue silently.

## Setup: Granola API key (one-time)

This skill uses Granola's **official public API** (`https://public-api.granola.ai/v1`), authenticated with a personal API key. It no longer reads Granola's local token/credential store — recent Granola builds encrypt that store behind a key held in an app-entitled macOS Keychain item that no external script can read, so the old approach is permanently broken.

**Generate a key once** (any workspace member on a **Business** plan can):
1. Granola desktop app → Settings → Connectors → API keys → Create new key. Grant it the **Personal notes** scope (owned or directly-shared notes); add **Public notes** too if you want workspace-visible notes. The key looks like `grn_...`.
2. Store it (kept outside this skill's git repo so it's never committed):
   ```bash
   mkdir -p ~/.config/granola-summarise \
     && printf 'grn_XXXX' > ~/.config/granola-summarise/api-key \
     && chmod 600 ~/.config/granola-summarise/api-key
   ```
   The `GRANOLA_API_KEY` environment variable overrides the file if set.

If no key is configured, `granola.py` exits with these exact instructions. If the plan doesn't offer API keys, this skill can't run — fall back to pasting the transcript from Granola manually.

## Workflow

### Step 1: Check for recent calls

Always start by running the check command:

```bash
python3 ~/.claude/skills/summarise-granola/scripts/granola.py check
```

This returns JSON with one of two modes:

**Auto mode** (call ended within 30 minutes):
```json
{"mode": "auto", "id": "...", "title": "Meeting Title", "minutes_ago": 15.2}
```
→ Proceed directly to extract and summarise this meeting.

**Select mode** (no recent call):
```json
{"mode": "select", "meetings": [
  {"number": 1, "id": "...", "title": "Meeting A", "date": "2026-01-05"},
  {"number": 2, "id": "...", "title": "Meeting B", "date": "2026-01-04"},
  ...
]}
```
→ Present the numbered list to the user and ask which one to summarise. User can reply with just "1", "2", etc.

**Processing delay:** the official API only returns notes that already have a generated AI summary **and** transcript. A call that just ended may not appear in `check`/`list` (or may 404 on `get`) until Granola finishes processing it. If a call the user just finished is missing, wait ~1 minute and retry before assuming it isn't there.

### Step 2: Extract the transcript

Once you have the meeting ID (from auto mode or user selection), extract the transcript:

```bash
python3 ~/.claude/skills/summarise-granola/scripts/granola.py get <document_id>
```

Or by number if user selected from the list:

```bash
python3 ~/.claude/skills/summarise-granola/scripts/granola.py recent <n>
```

The transcript is automatically saved to `data/transcripts/`.

### Step 2.3: Apply STT corrections

Run the context-aware STT corrections script on the saved transcript:

```bash
python3 ~/.agents/scripts/utils/apply-stt-corrections.py <transcript-path>
```

This applies corrections from `~/.agents/references/stt-corrections.json` — fixing known STT errors for org names, person names, and acronyms. Scoped corrections (entries with a `context` field) only apply when at least one context keyword appears in the transcript. Changes are printed to stderr; if any were made, note them briefly in the Step 6 report.

### Step 2.5: Confirm participant names

Before creating the tidied transcript and summary, confirm the names of all participants.

**Check the meeting title first:**

If the meeting title contains clear participant names (e.g., "Jane Smith & Your Name", "Call with Sarah Chen"), extract those names.

**If names are unclear:**

If the meeting title is generic (e.g., "Weekly sync", "Project check-in", "Team meeting") or doesn't contain recognisable names, ask the user using AskUserQuestion:

```
"Who were the participants in this call? (I'll use these names in the transcript and summary)"
```

Provide a free-text input option since participant names can't be predicted.

**Important:** Never guess participant names. The Granola transcript only shows "Me" and "Other" as speaker labels, which doesn't identify the other person. If in doubt, ask.

**Store the confirmed names** and use them consistently throughout the tidied transcript and summary.

### Step 2.6: Ask about sharing (before parallel work)

For 1:1 calls where the other participant has a clear name, ask the sharing questions **now**—before launching any background agents. This must happen in its own message so the user sees it immediately.

**Skip this step for:** group meetings (more than 2 participants), meetings without a clear person name, or internal/solo sessions.

**Saved defaults (skip or fast-path):** the same person is usually shared with the same way, so check for saved per-person defaults before asking.

1. Derive the person key from the confirmed name (lowercase, hyphenated — "Jane Smith" → `jane-smith`) and read any saved defaults:
   ```bash
   python3 ~/.claude/skills/summarise-granola/scripts/share_defaults.py get <person-key>
   python3 ~/.claude/skills/summarise-granola/scripts/share_defaults.py summary <person-key>
   ```
   `get` prints the saved choices as JSON (`{}` if none); `summary` prints a one-line label like `doc + Slack DM · no comment · auto-send`.
2. **If the request asked to reuse defaults** — the invocation or a recent message contains "use share defaults", "use my usual", "usual settings", "use defaults", or similar — AND saved defaults exist: **skip the AskUserQuestion entirely** and apply the saved choices (one exception: if the saved comment is `add_comment`, still ask only for the comment text — the text itself is never stored). Note in the Step 6 report that saved defaults were applied (show the summary label). If nothing is saved yet, fall through to asking.
3. **If defaults exist but weren't explicitly requested:** offer a one-tap fast-path first — a single-select AskUserQuestion "Use your usual settings for [Name]? (`<summary label>`)" with options **"Use usual settings"** and **"Customise…"**. On "Use usual settings", apply the saved choices and skip the three questions. On "Customise…", ask the three questions below.
4. **If nothing is saved:** ask the three questions below as normal.

When applying saved defaults, map the tokens back to behaviour: `sharing` → which of doc / email / Slack DM / tidied transcript; `comment: no_comment` → no comment; `comment: add_comment` → still ask for the comment text (the text itself is never stored); `approval: auto_send` → treat as "Auto-send when ready"; `approval: preview` → show a preview first.

**Ask all three questions in a single AskUserQuestion call.** The user nearly always sends via email or Slack, so the flow is built around that assumption: present the sharing, comment, and approval questions together up front rather than asking comment/approval as a slow follow-up round. One round-trip means the answers come back instantly and the rest of the workflow can run unattended. If the user ends up choosing "Skip" for sharing, just ignore the comment and approval answers.

Question 1 — **Sharing** (`multiSelect: true`):
- **"Add summary + raw transcript to meeting doc"** — always show for 1:1 calls. Inserts the summary into the "Call summaries" tab AND the raw transcript (with speaker labels substituted for the confirmed participant names) into the "Call transcripts" tab.
- **"Send call notes email to [Person Name]"** — always show for 1:1 calls
- **"Send call notes Slack DM to [Person Name]"** — always show for 1:1 calls
- **"Create tidied transcript"** — always show (off by default). Fire-and-forget background agent that runs AFTER the main workflow finishes (Step 8). Does not block the gdoc insert or the Slack/email send.
- **"Skip"** — always show, and is the default only when the user is explicitly shown the options and submits an empty response; it is not the default when the question was never asked.

Question 2 — **Comment** (single-select):
- **"No comment"**
- **"Add a comment"** — the user will type the comment via the free-text option

Question 3 — **Approval** (single-select):
- **"Auto-send when ready"** — skip the final preview/confirmation and send as soon as the summary and gdoc edit are done. **Keep this exact label** ("Auto-send when ready"): a PostToolUse hook (`autosend-grant.py`) detects it and waves the email send through the bash-safety confirmation, so the auto-send actually sends without a second permission prompt.
- **"Show preview first"** — show a preview and wait for explicit confirmation before sending

**If the user picks "Auto-send when ready", do NOT ask for confirmation again in Steps 7b or 7c — just send.** The user has pre-authorised the send, and the security hook is primed to allow it.

**Codex fallback:** If `AskUserQuestion` or multi-select questions are unavailable, ask the sharing question as a normal chat message and STOP until the user answers. Do not start summary generation, project filing, gdoc insertion, email, Slack, or tidied-transcript work before the user has answered. For 1:1 calls, do not treat silence or lack of tool support as "Skip".

**Important:** This AskUserQuestion call MUST be sent alone (not bundled with Agent or Bash tool calls in the same message). If it's sent in parallel with background agents, the user won't see it until all parallel calls complete, defeating the purpose.

Hold all answers (sharing selections, comment, auto-send preference) for use in Steps 4 and 7.

**Save the choices as defaults.** Whenever the three questions were actually asked (i.e. not skipped via saved defaults) and this is a 1:1 with a clear person, persist the answers so next time can reuse them:

```bash
python3 ~/.claude/skills/summarise-granola/scripts/share_defaults.py set <person-key> \
  --sharing "<comma-separated: meeting_doc,email,slack_dm,tidied_transcript>" \
  --comment <no_comment|add_comment> --approval <auto_send|preview>
```

On a Skip choice, pass `--sharing ""` with whatever comment/approval the user submitted (or skip the save entirely — a Skip default isn't very useful). This writes `share_defaults` onto the person's registry entry (creating a minimal entry if they aren't registered yet). Because `~/.agents/data/people.json` lives in the `~/.agents` repo, add it to the Step 5.5 autocommit file list (or commit it directly) so the saved default persists across machines.

Defaults accrue only from this normal Step 2.6 flow. The late-ask fallback paths (Steps 4/7b/7c, reached only when participant names were unclear back at Step 2.5) deliberately don't call `set` — that's fine, not an oversight.

### Step 3: Launch summary agent and pre-fetch (parallel)

Launch the summary agent alongside pre-fetch work in a single message to minimise wall-clock time to a sent Slack/email.

**Do NOT launch the tidied transcript agent here.** The tidied transcript agent runs at the very end (Step 8) as a fire-and-forget background task, AFTER the gdoc insert and Slack/email have been sent. This keeps it off the critical path entirely.

**Summary agent** (`model: "opus"`)

Before launching, `Read` `references/summary-format.md` — paste its full contents verbatim into the agent prompt. The agent has no access to skill files, so the guidelines must travel with the prompt.

Prompt the agent with: the full raw transcript text, the confirmed participant names, the summary-format contents, and an instruction to write the result to `data/summaries/` using the same filename as the transcript (with `--summary.md` suffix).

**Pre-fetch: People registry + Google Doc tab contents** (Bash, in parallel with the agent)

Before the agent finishes, look up the other participant in the people registry and pre-fetch the current contents of both gdoc tabs. Run these **in the same message as the agent launch:**

1. Read the people registry: `cat ~/.agents/data/people.json`
2. If the person is registered and has a `meeting_doc`, also start reading both tabs (each tab goes to its own file so anchor detection in Step 4c stays straightforward):
   ```bash
   gdoc cat <doc_id> --tab "Call summaries"   > /tmp/gdoc-summary-tab.txt
   gdoc cat <doc_id> --tab "Call transcripts" > /tmp/gdoc-transcript-tab.txt
   ```
   If either tab doesn't exist the call fails — that's fine, just proceed; Step 4c treats missing output as "tab empty or absent".

Store the results (person registry data, project association, tab contents) for use in Steps 4, 5, and 7.

**Progression:** The summary agent blocks progression to Step 4. The pre-fetch runs concurrently with it.

### Step 4: Add summary and raw transcript to meeting doc (if selected)

**Skip this step** if the user did not select "Add summary + raw transcript to meeting doc" in Step 2.6, or if this is a group meeting / meeting without a clear person name.

**Why this happens before project association:** the meeting doc is the most visible deliverable and the most useful thing to share with the other participant. Getting it written to Google Docs first means that even if the project-association question in Step 5 is mis-answered or skipped, the canonical content is already landed in the right place.

**Two inserts:** the summary goes into the "Call summaries" tab, and the raw transcript (with Me/Other substituted for the confirmed participant names) goes into the "Call transcripts" tab. Both happen in this step.

**Step 4a: Look up the meeting doc**

```bash
python3 ~/.claude/skills/summarise-granola/scripts/find_meeting_doc.py --name "<Full Name>"
```

Returns JSON on stdout: `{"doc_id": "...", "source": "registry|search|not_found", "person_key": "..."}`. The script checks the registry first, falls back to `gdoc find "ph-<initials>" --title`, and caches any search hit back into `people.json` automatically.

If the person is not in the registry, also pass `--initials <xx>` (e.g., `--initials mb` for "Matt Brooks"). If `source: not_found`, tell the user and skip this step.

**Step 4b: Prepare the gdoc insert files**

```bash
python3 ~/.claude/skills/summarise-granola/scripts/prepare_gdoc_inserts.py \
  --summary <summary-path> --transcript <raw-transcript-path> \
  --user-first <user-first-name> --other-first <other-first-name> \
  --date YYYY-MM-DD
```

Writes `/tmp/gdoc-summary.txt` and `/tmp/gdoc-raw-transcript.txt`. The script strips `---` lines, collapses blank lines around `##` headings, rewrites the summary heading block to `# YYYY-MM-DD`, substitutes `**Me**:`/`**Other**:` in the raw transcript, and validates post-conditions (first line is `# YYYY-MM-DD`, no residual `---` or `**Me**:`/`**Other**:`). Non-zero exit + stderr on any mismatch — if that happens, stop and surface the error.

**Step 4c: Push each file to its tab**

**Default to `gdoc edit` when the tab already has content** — it preserves formatting better than `gdoc insert` on populated tabs (where `insert` has been observed to cause formatting problems). Use `gdoc insert --position start` **only when the tab is empty** (or doesn't exist yet — in which case `insert` auto-creates it cleanly).

Decide per tab based on the pre-fetched content from Step 3 (`/tmp/gdoc-summary-tab.txt` and `/tmp/gdoc-transcript-tab.txt`):

1. **Detect the anchor (`ANCHOR_TEXT`).** The anchor is the first real line of content in the tab — in these docs always a level-1 heading (the previous call's `# YYYY-MM-DD`, or `# Meeting summary: ...`). `gdoc edit` matches against **raw text**, so `ANCHOR_TEXT` must be the heading text *without* the `#`. Read it from the `--plain` export, which is exactly the matchable form regardless of gdoc version (older `gdoc cat` dropped the `#` on read; patched versions keep it — `--plain` sidesteps that entirely). Skip the `account:` / `--- first interaction ---` / ` 📄 …` status lines `gdoc` prepends; the first non-blank line after them is the anchor:
   ```bash
   ANCHOR_TEXT=$(gdoc cat --plain <doc_id> --tab "Call summaries" | grep -m1 .)
   ```
   If there's no real content line, treat the tab as empty (use the `gdoc insert` path in step 3).

2. **If the tab is populated (anchor found) → use `gdoc edit`:**

   `gdoc edit` **matches against raw document text** (no markdown — a heading matches as its plain text, so a `#`-prefixed match string returns "no match"), but **renders the replacement as markdown**. So the old-file must be the plain `ANCHOR_TEXT`, while the new-file's trailing anchor must carry the `# ` prefix — otherwise the existing heading is rebuilt as a plain paragraph and **loses its heading style** (a real bug that has happened; the `--plain` read above guarantees `ANCHOR_TEXT` has no stray `#` to leak into the match).

   Run this block **once per tab**, recomputing all three variables each time — `ANCHOR_TEXT` is re-read per tab (step 1) and the two `/tmp` paths differ per tab. For "Call summaries": `NEW_FILE=/tmp/gdoc-summary.txt`, `OLD_FILE=/tmp/gdoc-summary-old.txt`. For "Call transcripts": `NEW_FILE=/tmp/gdoc-raw-transcript.txt`, `OLD_FILE=/tmp/gdoc-transcript-old.txt`, and read the anchor with `--tab "Call transcripts"`.

   ```bash
   ANCHOR_TEXT=$(gdoc cat --plain <doc_id> --tab "Call summaries" | grep -m1 .)   # matchable text, no leading "# "
   NEW_FILE=/tmp/gdoc-summary.txt
   OLD_FILE=/tmp/gdoc-summary-old.txt

   # Trailing anchor in the NEW file keeps the "# " so the old heading stays a heading.
   printf '\n# %s' "$ANCHOR_TEXT" >> "$NEW_FILE"
   # OLD file is the PLAIN matchable text (no "# ") so the match succeeds.
   printf '%s' "$ANCHOR_TEXT" > "$OLD_FILE"   # no trailing newline

   gdoc edit <doc_id> --tab "Call summaries" --old-file "$OLD_FILE" --new-file "$NEW_FILE"
   ```
   The plain `ANCHOR_TEXT` must match exactly one place in the tab — the first line of existing content is always unique enough. If `gdoc edit` reports more than one match (or zero), stop and inspect rather than forcing it. **After the edit, verify heading preservation** with `gdoc toc <doc_id> --tab "Call summaries"`: both the new `YYYY-MM-DD` and the previous anchor date must still appear as headings. If the previous date is missing from the TOC, the trailing `# ` was dropped. To re-run, **first regenerate the new file via Step 4b** (`prepare_gdoc_inserts.py`) — the `>>` append is destructive on repeat and would otherwise stack a second trailing anchor — then redo the printf + `gdoc edit` block.

3. **If the tab is empty or absent → use `gdoc insert`:**
   ```bash
   gdoc insert <doc_id> --tab "Call summaries" --position start /tmp/gdoc-summary.txt
   ```

Apply the same logic to the "Call transcripts" tab using `/tmp/gdoc-transcript-tab.txt` and `/tmp/gdoc-raw-transcript.txt`.

Run the two tabs' pushes as separate Bash calls in the same message (independent, can parallelise). If the "Call transcripts" tab's `gdoc edit`/`gdoc insert` fails entirely (e.g. tab doesn't exist and insert couldn't create it), note it in the final report and continue; the summary push is what matters.

**Step 4d: Record the "Call summaries" tab URL**

```bash
gdoc tabs <doc_id> --json | python3 -c "import json,sys; print(next(t['id'] for t in json.load(sys.stdin)['tabs'] if t['title']=='Call summaries'))"
```

Construct `https://docs.google.com/document/d/<doc_id>/edit?tab=<tab_id>` and cache it for Step 6 (reporting) and Step 7 (email/Slack).

**Critical `gdoc` invariant:** Never use `gdoc pull` / `gdoc push` / `gdoc write` on multi-tab docs — they flatten tabs and destroy structure. Only `gdoc insert --tab` and `gdoc edit --tab` are safe.

### Step 5: Associate with project

Now that the meeting doc is updated, determine if this call should also be filed under a project folder. **Use the people registry data pre-fetched in Step 3** — do not re-read `people.json` here.

**Step 5a: Check the people registry**

1. Extract the other participant's name from the meeting title (the person who isn't the user)
2. Convert to registry key format: lowercase, hyphenated (e.g., "Jane Smith" → "jane-smith")
3. Use the registry data already fetched in Step 3 (if not pre-fetched, read it now: `cat ~/.agents/data/people.json`)
4. Check if the key exists in `people` and has a `default_project` value

**Step 5b: If person is registered → auto-associate**

If found in the registry:
1. Get the `default_project` value
2. Silently associate with that project (no confirmation needed)
3. Note the auto-association for the final output (Step 6)

**Step 5c: If person is NOT registered → show project list**

If not found in the registry, fall back to the full project selection. Read the central project index:

```bash
cat ~/Documents/Projects/projects.yaml
```

Filter to only `status: active` projects and present options using AskUserQuestion:
- List each active project as an option (e.g., "Acme Consulting")
- Include a "None" option for calls not associated with any project

**Step 5d: Copy files to project**

For both auto-associated and manually selected projects:

1. Get the project's `folder` value (from registry's `default_project` or selected project's JSON)
2. The project directory is: `~/Documents/Projects/{folder}/`
3. Create the subdirectory if it doesn't exist: `{project_dir}/calls/summaries/`
4. Copy the summary: `{project_dir}/calls/summaries/{slug}--summary.md`

Example:
```bash
mkdir -p ~/Documents/Projects/acme-consulting/calls/summaries
cp ~/.claude/skills/summarise-granola/data/summaries/2026-01-06-meeting--summary.md ~/Documents/Projects/acme-consulting/calls/summaries/
```

**Store `{project_dir}` in memory for Step 8** (the tidied transcript agent will handle its own copy into `{project_dir}/calls/transcripts/` when it finishes, to avoid blocking the main workflow).

**Step 5e: Offer to register unregistered people**

If the user selected a project for someone NOT in the registry, offer to add them:

> "Would you like me to register [Name] with [Project] for future calls?"

If yes, update `people.json` to add or update the entry with the `default_project` value. If Step 4 cached a `meeting_doc` for this person but the rest of the entry wasn't created yet, include that too.

**If user selects "None":** No additional action needed, and don't offer registration.

### Step 5.5: Auto-commit saved data and project files

**Always run this**, right after the summary is saved and any project copy is made — even when the call was not associated with a project (the `data/` files must still be committed).

Pass every file that now exists to the autocommit helper in a single call:

```bash
bash ~/.claude/skills/summarise-granola/scripts/autocommit.sh \
  -m "granola: {slug} — transcript + summary" \
  ~/.claude/skills/summarise-granola/data/transcripts/{slug}.md \
  ~/.claude/skills/summarise-granola/data/summaries/{slug}--summary.md \
  {project_dir}/calls/summaries/{slug}--summary.md
```

- The **raw transcript** and **summary** (both under `data/`) resolve to the `~/.agents` repo — committed and pushed to origin.
- The **project summary copy** resolves to the project's own repo — committed only (project repos are local-only, no remote).
- **Include the project-copy path only if Step 5 associated a project.** If the user chose "None" (or the person wasn't matched), omit that third path and commit just the two `data/` files.

The helper groups files by their owning git repo, resolves the `~/.claude` → `~/.agents` symlink, skips any files that are missing/gitignored/not in a repo, commits only the given paths (never sweeping other staged changes), makes no empty commits, and treats a push hiccup as non-fatal. It prints one line per repo to stderr: `committed in <root>`, `pushed <root>`, `nothing to commit in <root>`, or a failure line. **Report the Step 6 outcome from what the helper actually printed** — don't assume success. E.g. if it printed `committed in .../.agents` + `pushed` and `committed in .../coaching-jane`, report "Committed to `~/.agents` (pushed) + `coaching-jane`"; if a repo printed a failure/skip line, say so.

### Step 6: Report saved files and open them

When reporting the files saved, always use **full expanded paths** (not relative paths or paths with `~`). This allows the user to control-click/command-click on the path in their terminal to open the file.

**Include, in this order:**
1. **Meeting doc link** (if Step 4 ran) — the "Call summaries" tab URL from Step 4d. If the raw transcript insert also succeeded, mention that inline ("Raw transcript added to 'Call transcripts' tab.").
2. **Files saved** — full absolute path of the summary in the project folder.
3. **Auto-association note** (when applicable) — e.g. `Auto-associated with **Acme Consulting** (Jane Smith is registered to this project)`
4. **Tidied transcript note** (only if selected) — e.g. `Tidied transcript is generating in the background and will be saved to [paths] when done.`

**Good:**
```
Summary inserted at top of the "Call summaries" tab: https://docs.google.com/document/d/.../edit?tab=t.xxxx

Files saved:
- /Users/username/Documents/Projects/acme-consulting/context/calls/summaries/2026-01-09-meeting--summary.md

Auto-associated with **Acme Consulting** (Jane Smith is registered to this project)
```

**Bad:**
```
Files saved:
- context/calls/2026-01-09-meeting--summary.md
- ~/Documents/Projects/acme-consulting/context/calls/2026-01-09-meeting--transcript.md
```

**Open the summary file automatically:**

After copying files to a project, open the summary file:

```bash
open "/Users/username/Documents/Projects/acme-consulting/context/calls/summaries/2026-01-09-meeting--summary.md"
```

### Step 7: Send call notes (email or Slack DM)

**Skip this step** if the user didn't select email or Slack DM in Step 2.6 (or if this is a group meeting / meeting without a clear person name).

**Step 7a: Check for early answer or ask now**

If the sharing question was already asked in Step 2.6 (and the user has answered), use that answer. If it wasn't asked yet (e.g., participant names were unclear at Step 2.5), ask now using AskUserQuestion with `multiSelect: true`:

- **"Send call notes email to [Person Name]"** — always show for 1:1 calls
- **"Send call notes Slack DM to [Person Name]"** — always show for 1:1 calls
- **"Skip"** — always show

If the user selects only "Skip", stop here.

**The "Call summaries" tab URL was already resolved in Step 4d.** Reuse it here — do not re-look it up.

**Step 7b: Send call notes email** (if selected)

**IMPORTANT:** Always use `gog gmail send` for sending emails (see `~/.agents/references/gog-cli.md`).

**a) Find the attendee's email address:**

1. Check `people.json` for an `email` field on the person's entry. If found, use it.
2. If not found, search Gmail using the **claude.ai Gmail MCP**:
   ```
   mcp__claude_ai_Gmail__gmail_search_messages
     q: "from:<person name> OR to:<person name>"
     maxResults: 3
   ```
   Then read the most recent message to extract the attendee's email from the headers:
   ```
   mcp__claude_ai_Gmail__gmail_read_message
     messageId: "<message_id>"
   ```
3. If Gmail search doesn't find a match, ask the user for the email address.
4. Once an email is obtained (from Gmail or the user), save it to the person's `email` field in `people.json` for future use.

**b) Comment:**

Use the comment answer collected in Step 2.6. Do NOT ask again. If Step 2.6 was skipped (e.g., names were unclear earlier), ask now using AskUserQuestion:

> "Would you like to add a comment to the call notes email?"

- Provide a "No comment" option and a free-text "Add a comment" option

**c) Send the email using `gog gmail send`:**

```bash
gog gmail send --to "<to>" --subject "Call notes" --body "<message>" --account your-email@gmail.com
```

- **To:** the attendee's email address
- **Subject:** `Call notes`
- **Message (without comment):**
  ```
  Hi <first name>,

  Summary of our call here:
  <call_summaries_tab_url>

  All the best,
  Peter
  ```
- **Message (with comment):**
  ```
  Hi <first name>,

  Summary of our call here:
  <call_summaries_tab_url>

  <user's comment>

  All the best,
  Peter
  ```

**Approval behaviour:**
- If the user selected **"Auto-send when ready"** in Step 2.6, skip the preview/confirmation and send immediately.
- Otherwise, show the user a preview of the email and ask for confirmation before sending.

**Step 7c: Send call notes via Slack DM** (if selected)

1. **Find the person's Slack DM channel:**
   - Check `people.json` for a `slack_dm_channel` field on the person's entry
   - The field is an object containing `channel_id`, `workspace`, `slack_connect`, and verified identity metadata (`user_id`, `verified_real_name`, `verified_email`, `verification_source`, `verified_for`, `verified_at`)
   - **Never treat a cached channel ID as proof of identity.** Before every send, resolve the channel in its cached workspace via the Slack launcher (`~/.agents/skills/slack/scripts/slack -w <workspace> channels "im"`) and get its current `user` ID.
   - For ordinary workspace users, resolve that user via `... -w <workspace> users`. For `slack_connect: true`, follow the Slack skill's Slack Connect workflow instead: inspect DM history for a message from the channel's current `user` ID and use its embedded `user_profile`. If no attributable embedded profile is available, stop and ask the user rather than sending.
   - Accept the channel only when one of these checks passes:
     1. The live profile's `real_name` exactly matches the confirmed participant's full name, and the Slack skill's cross-workspace/Slack-Connect ambiguity check finds no other exact match.
     2. The current channel user ID, live `real_name`, and live email all match the entry's `user_id`, `verified_real_name`, and `verified_email`; `verification_source` is `"user"`; and `verified_for` exactly matches the current registry person key. If Slack does not expose an email for this user, stop and ask rather than treating the missing value as a match.
     3. The user explicitly supplied or confirmed this channel for this participant in the current conversation; record the resolved identity metadata before sending.
   - A first-name-only profile, a matching first name, or a cached `channel_id` without verified identity metadata is insufficient. If the workspace or profile conflicts with known context (for example, an employee of one organisation mapped to a different organisation's workspace), stop and ask even if another check appears to pass.
   - If no usable cached mapping exists, search for the person:
     - Run `~/.agents/skills/slack/scripts/slack -w <workspace> users` and parse the JSON. Always use the launcher, not `slack_client.py` directly.
     - **Full name verification (CRITICAL):** Match against `real_name` (full name), NOT just `name`, display name, or first name. The person's full name from the meeting title must exactly match a workspace member's `real_name`. If no exact full-name match is found, do NOT proceed—ask the user to identify the correct person.
     - Once the correct user is identified, find their DM channel via `~/.agents/skills/slack/scripts/slack -w <workspace> channels "im"` and match by user ID.
   - Cache the channel plus resolved `user_id`, `verified_real_name`, `verified_email`, `verification_source` (`"exact_name"` or `"user"`), `verified_for` (the registry person key), and `verified_at` in `people.json`. Only mark a non-exact-name mapping as `"user"` after explicit user confirmation for that exact registry person.

2. **Comment:** use the comment answer collected in Step 2.6. Do NOT ask again. If Step 2.6 was skipped (e.g., names were unclear earlier), ask now using AskUserQuestion: "Would you like to add a comment to the Slack DM?" with a "No comment" option and a free-text "Add a comment" option.

3. **Compose message** using Slack mrkdwn formatting — keep it brief (no greeting or sign-off):
   - **Without comment:**
     ```
     Summary of our call here:
     <call_summaries_tab_url>
     ```
   - **With comment:**
     ```
     Summary of our call here:
     <call_summaries_tab_url>

     <user's comment>
     ```

4. **Approval behaviour:**
   - If the user selected **"Auto-send when ready"** in Step 2.6, skip the preview/confirmation and send immediately.
   - Otherwise, **show preview and ask for confirmation** before sending. The preview MUST show the recipient's full Slack profile name (e.g., "Send to **Jane Smith** on hartreeworks?"). If the Slack profile name differs from the expected name from the meeting title, flag this explicitly as a potential mismatch.

5. **Send via Slack** (always pass the workspace from the cached entry and use the launcher):
   ```bash
   ~/.agents/skills/slack/scripts/slack -w <workspace> send "<channel_id>" "<message>"
   ```

6. Report success or failure to the user.

### Step 8: Launch tidied transcript agent (background, fire-and-forget)

**Skip this step** if the user did not select "Create tidied transcript" in Step 2.6.

Launch with `Agent(model: "sonnet", run_in_background: true)`. This is the last thing you do — the gdoc insert and Slack/email are already sent. When the agent finishes later, its completion notification can be acknowledged with a one-liner (e.g. "Tidied transcript saved to X.").

**Agent prompt (must be self-contained — the agent has no access to this skill file):**

Before launching, `Read` `references/tidying-instructions.md` and paste its contents verbatim into the prompt.

Include:
1. The **full raw transcript text** (paste inline from `data/transcripts/{slug}.md`).
2. The **confirmed participant names** from Step 2.5.
3. Instruction to write the tidied transcript to: `~/.claude/skills/summarise-granola/data/tidied-transcripts/{slug}--transcript.md`
4. If a project folder was determined in Step 5, also instruct the agent to copy the final file to: `~/Documents/Projects/{folder}/calls/transcripts/{slug}--transcript.md` (after creating the parent directory with `mkdir -p`).
5. The tidying guidelines from `references/tidying-instructions.md` (pasted verbatim).
6. Instruction to **auto-commit** the tidied transcript once written (and copied). Because this agent runs in the background after the main workflow, it must commit its own output — the main loop is no longer around to do it. Run:
   ```bash
   bash ~/.claude/skills/summarise-granola/scripts/autocommit.sh \
     -m "granola: {slug} — tidied transcript" \
     ~/.claude/skills/summarise-granola/data/tidied-transcripts/{slug}--transcript.md \
     ~/Documents/Projects/{folder}/calls/transcripts/{slug}--transcript.md
   ```
   Omit the second path if no project folder was determined. The helper commits the `data/` file to `~/.agents` (and pushes) and commits the project copy to the local-only project repo.

## File locations

- **Raw transcripts:** `~/.claude/skills/summarise-granola/data/transcripts/`
- **Tidied transcripts:** `~/.claude/skills/summarise-granola/data/tidied-transcripts/`
- **Summaries:** `~/.claude/skills/summarise-granola/data/summaries/`

Files use the pattern:
- Raw transcripts: `YYYY-MM-DD-meeting-title-slug.md`
- Tidied transcripts: `YYYY-MM-DD-meeting-title-slug--transcript.md`
- Summaries: `YYYY-MM-DD-meeting-title-slug--summary.md`

The `data/` directory is inside the `~/.agents` git repo. All files written here — and any project-folder copies — are auto-committed by `scripts/autocommit.sh` (see the auto-commit note at the top, Step 5.5, and Step 8). `~/.agents` commits are also pushed to origin; project-repo commits are local-only.

## Transcript format

- `**Me**:` - User's microphone (the person running Granola)
- `**Other**:` - System audio (other participants)

## User info

Replace "YOUR_NAME" with the user's actual name. Always use their preferred name format in summaries.

## Script reference

| Command | Description |
|---------|-------------|
| `check` | Check for recent call or list 5 most recent for selection |
| `list` | List all meetings with transcripts |
| `get <id>` | Get transcript by document ID |
| `recent [n]` | Get nth most recent transcript (default: 1) |

**Helper scripts:**

| Script | Description |
|--------|-------------|
| `scripts/autocommit.sh -m "msg" FILE...` | Commit each file into its owning git repo (groups by repo root); pushes repos that have an `origin` remote (→ `~/.agents`), commits local-only project repos without pushing. Skips missing/gitignored files, makes no empty commits, push failures non-fatal. `--no-push` to commit without pushing. |

## Tips

- For long meetings, consider summarising in sections
- Ask what the user wants to focus on if the meeting covered multiple topics
- Include participant names from the meeting title when relevant

## People registry

The registry at `~/.agents/data/people.json` stores per-person metadata: default project associations and meeting doc references.

**Format:**
```json
{
  "people": {
    "jane-smith": {
      "full_name": "Jane Smith",
      "initials": "js",
      "default_project": "coaching-jane",
      "meeting_doc": {
        "url": "https://docs.google.com/document/d/...",
        "title": "ph-js Peter Hartree & Jane Smith meetings",
        "cached_at": "2026-01-20"
      }
    }
  }
}
```

**Key format:** Lowercase, hyphenated full name (e.g., "Jane Smith" → "jane-smith")

**Fields:**
- `full_name` — display name
- `initials` — lowercase initials for meeting doc lookup (e.g., "js", "ab")
- `email` — email address for sending call notes (Step 7b), or `null`
- `slack_dm_channel` — Slack DM details for sending call notes (Step 7c), or `null`. Object with `channel_id`, `workspace` (e.g. "hartreeworks", "acme-corp"), `slack_connect` (boolean), `user_id`, `verified_real_name`, `verified_email`, `verification_source` (`"exact_name"` or `"user"`), `verified_for` (the registry person key), and `verified_at`. Before every send, re-resolve the channel and apply Step 7c's three acceptance paths; user-confirmed alias mappings require the live user ID, name, and email to match the stored identity.
- `default_project` — project folder name for auto-association (Step 5), or `null`
- `meeting_doc` — Google Doc reference for call summaries (Step 4), or `null`

**Lookups:**
- **By name** (Step 5a): convert name to hyphenated key, check `people`
- **By initials** (Step 4a): scan `people` for matching `initials` field; if not found, search with `gdoc find "ph-{initials}" --title` and save the result

**Adding entries:**
- Automatically when a meeting doc is found via search
- When the user accepts the offer to register a person with a project (Step 5e)
- Manual edits
