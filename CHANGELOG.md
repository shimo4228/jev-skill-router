# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-09-21

### Changed

- Both requests now carry whole text. The wide pass ranks on each skill's full description
  instead of its first 60 characters, and the top three go back with the full body of their
  `SKILL.md` instead of its first 700. The 60-character index came from the cookbook, where
  it matches the width the agent it was written against displays in its own skill list;
  Claude Code shows the model the whole description, so ranking on a prefix ranked on less
  than the agent already sees. On a 59-skill roster, two descriptions fit in 60 characters.
- **More leaves your machine.** For the top three candidates, the whole text of `SKILL.md`
  is sent, including skills from a private project's `.claude/skills/`. See "What leaves
  your machine".
- `router_version` in the decision log is now `0.2.0`. Rows from 0.1.0 measured narrower
  inputs and are a different distribution; read them separately rather than pooled.
- The `INDEX_CHARS` and `EXCERPT_CHARS` constants and the arguments that carried them are
  gone. Nothing estimates a request's size before sending it: Jev's input budget is 64k
  tokens per request and 32k for the state plus the longest question, and a request over it
  comes back an error that the existing fail-open turns into one logged row and a quiet turn.

### Security

- A project skill is listed only when its `SKILL.md` resolves inside the repository level
  that holds the `.claude/skills` directory. Before this, a repository you cloned could link
  a `SKILL.md`, a skill directory, or `.claude/skills` itself to a file elsewhere on your
  machine and have its contents sent as a skill body (700 characters in 0.1.0). Symlinks in
  your own `~/.claude/skills/` and in plugins are still followed.

### Documentation

- The README now opens with what running it showed: a prompt hook cannot replace Claude
  Code's own skill selection, the cookbook's conditions do not carry over to a strong model
  that already sees whole descriptions, and the first real-session decisions were 3 sensible
  of 6. It points to `skillOverrides` and the early-access function hooks for anyone who
  wants to change the listing itself. Measurements for 0.2.0 replace the 0.1.0 figures.

### Fixed

- A decision log row now reports the fits score of the skill it actually suggested. When the
  `Choice` winner and the best-fitting candidate differed, `reason` printed the loser's score
  beside the winner's name (observed live: a suggestion whose own fits was 0.40 logged as
  "best fits 0.63"). A split is now named on both sides. The decision itself is unchanged.
- A fits key that is not on the menu sent can no longer fill a log row: the name printed in
  `reason` is bounded and quoted, the way an off-menu suggestion already was.

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
