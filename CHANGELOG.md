# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-09-21

First release, packaged as a Claude Code plugin.

- `UserPromptSubmit` hook that ranks the whole installed skill roster — user, plugin and
  project skills — with two TypeSafe Jev requests and returns at most one skill name.
- Three modes: `shadow` (default; records the decision, injects nothing), `inject` (adds a
  one-line pointer under a wall-clock budget) and `off`. Fail-open throughout: any failure
  becomes exit 0 with empty stdout and a logged reason.
- Configuration through the plugin's user config (`api_key`, `mode`, `log_path`) or the
  equivalent environment variables, which take precedence.
- JSONL decision log written 0600 into the plugin's data directory, carrying a hash of the
  prompt rather than its text, and never the API key.
