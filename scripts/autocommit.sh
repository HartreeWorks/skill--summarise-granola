#!/usr/bin/env bash
# autocommit.sh — commit (and push where a remote exists) the given files into
# their owning git repositories. Used by the summarise-granola skill to keep
# meeting transcripts and summaries backed up automatically.
#
# Usage: autocommit.sh [--no-push] -m "commit message" FILE [FILE ...]
#
# Behaviour:
#   * Groups files by their owning git repo (git rev-parse --show-toplevel), so a
#     single call can commit data-folder files (in ~/.agents) AND their project
#     copies (in a separate project repo) at once.
#   * Resolves symlinks in each path (pwd -P) before staging. This matters because
#     ~/.claude/skills is a symlink into ~/.agents/skills; git add refuses the
#     logical path ("outside repository") and only accepts the physical one.
#   * Skips files that don't exist, aren't inside a git repo, or are gitignored.
#   * Stages and commits ONLY the explicit files given (pathspec commit) — never
#     `git add -A`, and never sweeps other staged changes into the commit. Makes
#     no empty commits.
#   * Pushes repos that have an 'origin' remote (best-effort, non-fatal). This
#     auto-pushes ~/.agents; local-only project repos (no remote) are committed
#     but not pushed. On a rejected push (remote moved — e.g. the other Mac
#     pushed) it does one `pull --rebase --autostash` and retries, aborting the
#     rebase on conflict. Pass --no-push to commit everywhere without pushing.
#   * A push failure never fails the script — the local commit is the guarantee.
#
# Portable to bash 3.2 (macOS default): no associative arrays.

set -uo pipefail

msg=""
push=1
files=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-push) push=0; shift ;;
    -m) shift; msg="${1:-}"; [ $# -gt 0 ] && shift ;;
    --) shift; while [ $# -gt 0 ]; do files+=("$1"); shift; done ;;
    *) files+=("$1"); shift ;;
  esac
done

if [ -z "$msg" ] || [ ${#files[@]} -eq 0 ]; then
  echo "usage: autocommit.sh [--no-push] -m \"message\" FILE [FILE ...]" >&2
  exit 2
fi

# Validate files into parallel arrays (physical abs path + owning repo root).
valid_abs=()
valid_root=()
for f in "${files[@]}"; do
  if [ ! -e "$f" ]; then
    echo "autocommit: skip (missing): $f" >&2
    continue
  fi
  # pwd -P resolves symlinks so the path sits under the repo's real worktree.
  abs="$(cd "$(dirname "$f")" && pwd -P)/$(basename "$f")"
  dir="$(dirname "$abs")"
  root="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || {
    echo "autocommit: skip (not in a git repo): $f" >&2
    continue
  }
  if git -C "$dir" check-ignore -q -- "$abs"; then
    echo "autocommit: skip (gitignored): $f" >&2
    continue
  fi
  valid_abs+=("$abs")
  valid_root+=("$root")
done

if [ ${#valid_abs[@]} -eq 0 ]; then
  echo "autocommit: no committable files" >&2
  exit 0
fi

# Push current branch; on rejection, rebase on top of origin once and retry.
push_repo() {
  root="$1"
  git -C "$root" push -q origin HEAD 2>/dev/null && return 0
  branch="$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  [ -n "$branch" ] || return 1
  if git -C "$root" pull --rebase --autostash -q origin "$branch" >/dev/null 2>&1; then
    git -C "$root" push -q origin HEAD 2>/dev/null && return 0
  else
    git -C "$root" rebase --abort >/dev/null 2>&1 || true
  fi
  return 1
}

overall=0
roots="$(printf '%s\n' "${valid_root[@]}" | sort -u)"
while IFS= read -r root; do
  [ -n "$root" ] || continue

  # Collect every valid file whose owning repo is this root.
  paths=()
  i=0
  while [ "$i" -lt "${#valid_abs[@]}" ]; do
    if [ "${valid_root[$i]}" = "$root" ]; then
      paths+=("${valid_abs[$i]}")
    fi
    i=$((i + 1))
  done

  if ! git -C "$root" add -- "${paths[@]}"; then
    echo "autocommit: git add failed in $root" >&2
    overall=1
    continue
  fi

  if git -C "$root" diff --cached --quiet -- "${paths[@]}"; then
    echo "autocommit: nothing to commit in $root" >&2
    continue
  fi

  # Commit ONLY these paths — leaves any unrelated staged changes untouched.
  if ! git -C "$root" commit -q -m "$msg" -- "${paths[@]}"; then
    echo "autocommit: commit failed in $root" >&2
    overall=1
    continue
  fi
  echo "autocommit: committed in $root" >&2

  if [ "$push" -eq 1 ] && git -C "$root" remote get-url origin >/dev/null 2>&1; then
    if push_repo "$root"; then
      echo "autocommit: pushed $root" >&2
    else
      echo "autocommit: push failed for $root (commit is safe locally; push manually)" >&2
    fi
  fi
done <<< "$roots"

exit "$overall"
