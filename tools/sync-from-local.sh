#!/usr/bin/env bash
# sync-from-local.sh — one-way export from the live Claude Code harness (~/.claude)
# into this repo.
#
# jev-skill-router variant: the published payload is the router skill's runtime —
# its scripts, its tests, its SKILL.md and its packaging files. The published set
# is an explicit allowlist, not an origin sweep: every listed component must exist
# in the harness, and the SKILL.md must declare the expected origin marker, or the
# script aborts (it never silently drops a published component).
#
# Repo-root assets are never touched: .claude-plugin/, hooks/, tools/, README,
# CHANGELOG, .github/ and .gitignore belong to this repo, not to the harness.
#
# This script lives in tools/ rather than scripts/, because scripts/ is the
# plugin's Python runtime and is wholly owned by the sync.
#
# The script never commits — `git diff` in this repo is the review gate.
#
# Usage:
#   tools/sync-from-local.sh --dry-run   # report differences only
#   tools/sync-from-local.sh             # apply to working tree
#
# Config (env overrides):
#   HARNESS_SYNC_SOURCE  source harness dir      (default: ~/.claude)
#   HARNESS_SYNC_ORIGIN  origin value to require (default: shimo4228)

set -euo pipefail

SOURCE_DIR="${HARNESS_SYNC_SOURCE:-$HOME/.claude}"
ORIGIN="${HARNESS_SYNC_ORIGIN:-shimo4228}"
TARGET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_DIR="$SOURCE_DIR/skills/jev-skill-router"

# the fixed published set (allowlist)
SUBTREES=(scripts tests)                                  # harness skill dir -> repo root
ROOT_FILES=(pyproject.toml uv.lock LICENSE)               # harness skill dir -> repo root
SKILL_MD_TARGET="skills/jev-skill-router/SKILL.md"        # harness SKILL.md -> repo path

DRY_RUN=0
[[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]] && DRY_RUN=1

# Read the header into a variable first: piping head into grep can take head's SIGPIPE
# exit under `set -o pipefail` and spuriously fail. -F matches literally, so an
# overridden ORIGIN cannot act as a regex.
has_origin() {
  local header
  header="$(head -20 "$1")"
  grep -qF "origin: $ORIGIN" <<<"$header"
}

# --- guard: every published component must exist --------------------------------------
for f in "${ROOT_FILES[@]}"; do
  [[ -f "$SKILL_DIR/$f" ]] || { echo "ABORT: $SKILL_DIR/$f not found." >&2; exit 1; }
done
for d in "${SUBTREES[@]}"; do
  [[ -d "$SKILL_DIR/$d" ]] || { echo "ABORT: $SKILL_DIR/$d not found." >&2; exit 1; }
done
if [[ ! -f "$SKILL_DIR/SKILL.md" ]]; then
  echo "ABORT: $SKILL_DIR/SKILL.md not found — harness copy missing." >&2
  exit 1
fi
if ! has_origin "$SKILL_DIR/SKILL.md"; then
  echo "ABORT: $SKILL_DIR/SKILL.md does not declare 'origin: $ORIGIN'." >&2
  exit 1
fi

# --- guard: the shipped version must agree with the manifest --------------------------
# ROUTER_VERSION goes into every decision-log row. If it drifts from the version people
# installed, the rows stop identifying which build produced them — which is the one thing
# the log exists to support.
ROUTER_VERSION="$(sed -n 's/^ROUTER_VERSION = "\(.*\)"$/\1/p' "$SKILL_DIR/scripts/router.py")"
PLUGIN_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$TARGET_DIR/.claude-plugin/plugin.json" | head -1)"
PYPROJECT_VERSION="$(sed -n 's/^version = "\(.*\)"$/\1/p' "$SKILL_DIR/pyproject.toml" | head -1)"
if [[ -z "$ROUTER_VERSION" || -z "$PLUGIN_VERSION" || -z "$PYPROJECT_VERSION" ]]; then
  echo "ABORT: could not read one of the three versions" >&2
  echo "       router.py='$ROUTER_VERSION' plugin.json='$PLUGIN_VERSION'" >&2
  echo "       pyproject.toml='$PYPROJECT_VERSION'" >&2
  exit 1
fi
if [[ "$ROUTER_VERSION" != "$PLUGIN_VERSION" || "$ROUTER_VERSION" != "$PYPROJECT_VERSION" ]]; then
  echo "ABORT: version mismatch — scripts/router.py ROUTER_VERSION='$ROUTER_VERSION'," >&2
  echo "       .claude-plugin/plugin.json version='$PLUGIN_VERSION'," >&2
  echo "       pyproject.toml version='$PYPROJECT_VERSION'." >&2
  exit 1
fi

# --- guard: managed paths must be clean so the sync delta is reviewable ---------------
MANAGED=("${SUBTREES[@]}" "${ROOT_FILES[@]}" "$SKILL_MD_TARGET")
if (( ! DRY_RUN )); then
  if ! git -C "$TARGET_DIR" diff --quiet -- "${MANAGED[@]}" ||
     ! git -C "$TARGET_DIR" diff --cached --quiet -- "${MANAGED[@]}"; then
    echo "ABORT: uncommitted changes in the managed paths — commit or stash first," >&2
    echo "       so that 'git diff' after sync shows exactly the sync delta." >&2
    exit 1
  fi
fi

# --- staging --------------------------------------------------------------------------
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
mkdir -p "$STAGING/skills/jev-skill-router"

for d in "${SUBTREES[@]}"; do cp -R "$SKILL_DIR/$d" "$STAGING/"; done
for f in "${ROOT_FILES[@]}"; do cp "$SKILL_DIR/$f" "$STAGING/"; done
cp "$SKILL_DIR/SKILL.md" "$STAGING/$SKILL_MD_TARGET"

# --- prune runtime artifacts from the staged payload ----------------------------------
find "$STAGING" \( -name results.json -o -name '*.log' -o -name '*.pyc' \
  -o -name .DS_Store -o -name .coverage -o -name '.coverage.*' \) -delete
find "$STAGING" \( -name __pycache__ -o -name .pytest_cache -o -name .venv \
  -o -name node_modules -o -name .mypy_cache -o -name .ruff_cache \
  -o -name htmlcov \) -type d -prune -exec rm -rf {} + 2>/dev/null || true

# --- guard: no personal paths in the published payload --------------------------------
# The harness lives under the author's home directory. A path that leaked into a docstring
# or a fixture would ship to everyone who installs this.
if hits="$(grep -rIl "/Users/$(id -un)" "$STAGING" 2>/dev/null)"; then
  echo "ABORT: personal paths in staged payload:" >&2
  echo "$hits" >&2
  exit 1
fi

# --- secret scan (high-confidence patterns; abort on any hit) -------------------------
# pragma on the assignment: these are the scanner's own search patterns, not credentials
SECRET_RE='sk-ant-api[0-9A-Za-z_-]+|ghp_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{20,}|AKIA[0-9A-Z]{16}|xox[bporas]-[0-9A-Za-z-]{10,}|AIza[0-9A-Za-z_-]{35}|hf_[A-Za-z]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY'  # pragma: allowlist secret
if hits="$(grep -rEl "$SECRET_RE" "$STAGING" 2>/dev/null)"; then
  echo "ABORT: potential secrets detected in staged payload:" >&2
  echo "$hits" >&2
  exit 1
fi

# --- report / apply -------------------------------------------------------------------
if (( DRY_RUN )); then
  echo "# DRY-RUN (origin: $ORIGIN, version: $ROUTER_VERSION) — staging vs $TARGET_DIR"
  for d in "${SUBTREES[@]}"; do
    diff -rq "$STAGING/$d" "$TARGET_DIR/$d" 2>&1 || true
  done
  for f in "${ROOT_FILES[@]}"; do
    diff -q "$STAGING/$f" "$TARGET_DIR/$f" 2>&1 || true
  done
  diff -q "$STAGING/$SKILL_MD_TARGET" "$TARGET_DIR/$SKILL_MD_TARGET" 2>&1 || true
  exit 0
fi

for d in "${SUBTREES[@]}"; do
  rm -rf "${TARGET_DIR:?}/$d"
done
cp -R "$STAGING"/. "$TARGET_DIR"/

echo "# APPLIED (origin: $ORIGIN, version: $ROUTER_VERSION). Review before committing:"
git -C "$TARGET_DIR" status --short
