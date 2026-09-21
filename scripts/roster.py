"""Collect every skill Claude Code could load this turn into one flat roster.

Claude Code resolves skills from three places and the router has to see all three, or its
ranking silently omits whatever the agent is most likely to reach for in a project session:

  user    ``<config>/skills/<name>/SKILL.md``                       -> ``<name>``
  plugin  ``<installPath>/skills/<name>/SKILL.md`` for each plugin  -> ``<plugin>:<name>``
          that ``settings.json`` marks enabled
  project ``.claude/skills/<name>/SKILL.md`` from cwd up to the     -> ``<name>``
          repository root

The plugin side reads ``plugins/installed_plugins.json`` rather than walking
``plugins/cache/``: the cache keeps disabled plugins and superseded versions, and ranking a
skill the agent cannot load is worse than not ranking it at all.

A roster name is the **directory** name, not the frontmatter ``name``. Those usually agree,
and when they disagree the directory wins: the hookify plugin ships
``skills/writing-rules/SKILL.md`` whose frontmatter says ``writing-hookify-rules``, and the
name Claude Code offers is ``hookify:writing-rules`` (observed 2026-09-21). A suggestion the
agent cannot resolve is worse than no suggestion.

Frontmatter is parsed without PyYAML — this ships as a stdlib-only hook, and a skill whose
frontmatter we cannot read is skipped rather than allowed to take the roster down.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

#: This router never suggests itself.
SELF_NAME = "jev-skill-router"
#: The router's own root, used to exclude its SKILL.md by path as well as by name.
#:
#: The name alone stops being enough once this ships as a plugin: Claude Code offers a plugin
#: skill as ``<plugin>:<skill>``, so the very same file appears in the roster as
#: ``jev-skill-router:jev-skill-router`` and sails past a match on ``jev-skill-router``. Both
#: deployments put this package one level under the root — ``skills/jev-skill-router/scripts/``
#: in the harness, ``<install>/scripts/`` as a plugin — so one expression covers both, and it
#: keeps holding if the plugin is ever installed under a versioned directory name.
ROUTER_ROOT = Path(__file__).resolve().parents[1]

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):[ \t]*(.*)$")
_TRUE = {"true", "yes", "1", "on"}
#: A roster name reaches the model's context verbatim in inject mode, and a skill directory
#: under an untrusted repo's ``.claude/skills/`` is named by whoever wrote that repo. A name
#: with a newline in it renders as extra lines inside the ``<skill_relevance>`` block, which
#: is an instruction-injection path into the most trusted channel there is (rule
#: security.md: repo-controlled strings reaching the model). Only names the Skill tool can
#: address survive, so nothing usable is lost by dropping the rest.
#:
#: The tail anchor is ``\Z``, not ``$``: ``$`` also matches *before* a trailing newline, so
#: ``"evil\n"`` — a legal POSIX directory name, and a legal JSON plugin id — would clear a
#: ``$``-anchored check and carry its newline straight into the injected block. ``\Z`` is the
#: end of the string and nothing else.
_SKILL_NAME_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
#: Bucket under ``skills/`` that the claude.ai skill sync owns; its two-level layout and
#: frontmatter follow no convention this parser should guess at.
_SKIPPED_USER_DIRS = frozenset({"synced"})
#: Depth cap on the walk toward the repository root, so a pathological cwd cannot spin.
_MAX_PROJECT_LEVELS = 24


@dataclass(frozen=True)
class Skill:
    """One roster entry, in the shape both Jev questions consume.

    ``description`` and ``body`` are whole. The cookbook's 60-character index was the display
    width of the agent it was written against; Claude Code puts the entire description in the
    model's context, so a router that ranks on a prefix is ranking on less than the agent it
    is trying to help. On this machine's roster only two descriptions fit in 60 characters at
    all (59 skills, measured 2026-09-21).
    """

    name: str
    source: str  # "user" | "plugin" | "project"
    path: str
    description: str
    body: str


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ``(fields, body)``. Unparseable frontmatter yields ``({}, text)``.

    Handles the two shapes skill authors actually write: ``key: value`` and the folded
    ``key: >`` / ``key: |`` block whose value continues on the following indented lines.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fields: dict[str, str] = {}
    lines = match.group(1).splitlines()
    index = 0
    while index < len(lines):
        key_match = _KEY_RE.match(lines[index])
        index += 1
        if not key_match:
            continue
        key, raw = key_match.group(1), key_match.group(2).strip()
        if raw[:1] in ("|", ">"):
            block: list[str] = []
            while index < len(lines) and (not lines[index].strip() or lines[index][:1] in " \t"):
                block.append(lines[index].strip())
                index += 1
            fields[key] = " ".join(part for part in block if part)
        else:
            fields[key] = _unquote(raw)
    return fields, text[match.end() :]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _load_skill(skill_md: Path, name: str, source: str) -> Skill | None:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields, body = parse_frontmatter(text)
    if fields.get("disable-model-invocation", "").strip().lower() in _TRUE:
        return None
    description = " ".join((fields.get("description") or "").split())
    if not description:
        description = f"Skill {name}."
    return Skill(
        name=name,
        source=source,
        path=str(skill_md),
        description=description,
        body=body.strip(),
    )


def _scan_skills_dir(
    directory: Path,
    source: str,
    *,
    prefix: str = "",
    skip_dirs: Iterable[str] = (),
) -> list[Skill]:
    """Every ``<directory>/<name>/SKILL.md``. In the user's and a plugin's directory, symlinked
    entries are followed by design — a skill vendored by an external tool lives outside the
    skills dir (e.g. hunk-review).

    A project's ``.claude/skills`` belongs to whoever wrote the repo, and the whole SKILL.md is
    sent to the API as the skill's body. There a SKILL.md must resolve inside the repo level
    that holds this ``.claude/skills``, or a link to any readable file on the machine would
    be read and sent. The root is that level (``<level>/.claude/skills`` -> ``<level>``, which
    ``project_claude_dirs`` already resolved), not ``directory.resolve()``: a symlinked
    ``skills`` directory would carry a resolved root along to wherever it points."""
    skipped = set(skip_dirs)
    found: list[Skill] = []
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return found
    for entry in entries:
        if entry.name in skipped or not _SKILL_NAME_RE.match(entry.name) or not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        if source == "project" and not skill_md.resolve().is_relative_to(directory.parent.parent):
            continue
        skill = _load_skill(skill_md, f"{prefix}{entry.name}", source)
        if skill is not None:
            found.append(skill)
    return found


def enabled_plugins(settings_paths: Sequence[Path]) -> dict[str, bool]:
    """Merge ``enabledPlugins`` across a settings chain, lowest precedence first.

    A project can enable or disable a plugin for itself, so reading only the user's
    ``settings.json`` ranks skills the agent cannot load in that repo and hides ones it can
    — and the shadow log would carry that bias without ever saying so.
    """
    merged: dict[str, bool] = {}
    for path in settings_paths:
        block = _read_json(path).get("enabledPlugins")
        if isinstance(block, dict):
            merged.update({k: v for k, v in block.items() if isinstance(v, bool)})
    return merged


def enabled_plugin_dirs(
    manifest: Path | None, settings_paths: Sequence[Path]
) -> list[tuple[str, Path]]:
    """``(plugin-name, installPath)`` for every plugin the settings chain marks enabled.

    Plugin ids are ``<name>@<marketplace>``; the roster name uses only ``<name>``, which is
    how the Skill tool addresses a plugin skill.
    """
    installed = _read_json(manifest)
    enabled = enabled_plugins(settings_paths)
    if not isinstance(installed.get("plugins"), dict):
        return []
    out: list[tuple[str, Path]] = []
    for plugin_id, entries in sorted(installed["plugins"].items()):
        if enabled.get(plugin_id) is not True or not isinstance(entries, list) or not entries:
            continue
        install_path = (entries[0] or {}).get("installPath")
        plugin_name = plugin_id.split("@", 1)[0]
        if not install_path or not _SKILL_NAME_RE.match(plugin_name):
            continue
        out.append((plugin_name, Path(install_path)))
    return out


def project_claude_dirs(cwd: Path | None) -> list[Path]:
    """Every ``<level>/.claude`` from cwd up to and including the repo root, nearest first."""
    if cwd is None:
        return []
    try:
        current = cwd.resolve()
    except OSError:
        return []
    dirs: list[Path] = []
    for _ in range(_MAX_PROJECT_LEVELS):
        candidate = current / ".claude"
        if candidate.is_dir():
            dirs.append(candidate)
        if (current / ".git").exists() or current.parent == current:
            break
        current = current.parent
    return dirs


def project_skill_dirs(cwd: Path | None) -> list[Path]:
    """``.claude/skills`` at every level from cwd up to the repo root, nearest first."""
    return [d / "skills" for d in project_claude_dirs(cwd) if (d / "skills").is_dir()]


def settings_chain(base: Path | None, cwd: Path | None) -> list[Path]:
    """Settings files in increasing precedence: user, then each project level from the
    repo root down to cwd, ``settings.local.json`` last at each level."""
    chain: list[Path] = [base] if base is not None else []
    for claude_dir in reversed(project_claude_dirs(cwd)):
        chain.append(claude_dir / "settings.json")
        chain.append(claude_dir / "settings.local.json")
    return chain


def _read_json(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def build_roster(
    *,
    user_skills_dir: Path | None,
    plugins_manifest: Path | None,
    settings_path: Path | None,
    cwd: Path | None,
    exclude: Iterable[str] = (SELF_NAME,),
) -> list[Skill]:
    """The merged roster, sorted by name.

    Collected user -> plugin -> project so that a project skill overwrites a user skill of
    the same name, which is the order Claude Code itself resolves in.
    """
    merged: dict[str, Skill] = {}

    if user_skills_dir is not None:
        for skill in _scan_skills_dir(user_skills_dir, "user", skip_dirs=_SKIPPED_USER_DIRS):
            merged[skill.name] = skill
    for plugin_name, install_path in enabled_plugin_dirs(
        plugins_manifest, settings_chain(settings_path, cwd)
    ):
        for skill in _scan_skills_dir(install_path / "skills", "plugin", prefix=f"{plugin_name}:"):
            merged[skill.name] = skill
    # Outermost first, so the `.claude/skills` nearest the cwd is the one that wins — the
    # same way Claude Code resolves a name when a repo nests another one inside it.
    for directory in reversed(project_skill_dirs(cwd)):
        for skill in _scan_skills_dir(directory, "project"):
            merged[skill.name] = skill

    excluded = set(exclude)
    return sorted(
        (s for n, s in merged.items() if n not in excluded and not _is_self(s.path)),
        key=lambda s: s.name,
    )


def _is_self(path: str) -> bool:
    """True when this SKILL.md *is* the router's own, whatever name it carries in the roster.

    Matched against the two places the router's own SKILL.md sits rather than against the whole
    root: in the plugin layout ``ROUTER_ROOT`` is the plugin install directory, so a root-wide
    rule would also swallow every sibling skill the same plugin ships — silently, with no log
    line and no failing test until someone notices a skill missing from the roster.

    Resolved on both sides because a skill directory may be a symlink (``_scan_skills_dir``
    follows those by design) and because the harness runs out of git worktrees, where the same
    file is reachable by more than one spelling.
    """
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    #: ``ROUTER_ROOT/SKILL.md`` in the harness, ``ROUTER_ROOT/skills/<self>/SKILL.md`` as a
    #: plugin. Built per call so a test that repoints ``ROUTER_ROOT`` repoints these too.
    for candidate in (ROUTER_ROOT / "SKILL.md", ROUTER_ROOT / "skills" / SELF_NAME / "SKILL.md"):
        try:
            if resolved == candidate.resolve():
                return True
        except OSError:
            continue
    return False


def n_by_source(roster: Iterable[Skill]) -> dict[str, int]:
    counts = {"user": 0, "plugin": 0, "project": 0}
    for skill in roster:
        counts[skill.source] = counts.get(skill.source, 0) + 1
    return counts


def roster_hash(roster: Iterable[Skill]) -> str:
    """12 hex chars over the membership of the roster, independent of iteration order.

    The decision log carries this so a reader can tell "the suggestion changed" from
    "the roster changed underneath it".
    """
    joined = "\n".join(sorted(f"{s.source}|{s.name}" for s in roster))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
