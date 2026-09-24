"""Minimal stdlib client for the TypeSafe System One endpoint.

Wire format confirmed against the primary source https://docs.typesafe.ai/api.md
(as-of 2026-09-21):

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer <key>
    {"state": ..., "model": "jev-1.13.0", "questions": {"<id>": {"type": ..., ...}}}
    -> {"model": ..., "answers": {"<id>": {...}}, "usage": {"input_tokens", "output_tokens"}}

The success path was confirmed against the live API on 2026-09-21 (answers and ``usage`` came
back in the documented shape). Not yet observed live: the exact error body of a 4xx/5xx. It is
read defensively, so an unexpected shape degrades to a logged ``reason`` rather than a raised
exception on the hook path.

No retries. This runs in front of a human's prompt: the caller's budget is a few seconds and
a retried timeout just spends it twice. Failure is the caller's fail-open path.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import IO

DEFAULT_BASE_URL = "https://api.typesafe.ai"
#: The only non-loopback host this key may be sent to. ``TYPESAFE_BASE_URL`` can still move
#: the path or the port, but not the destination.
API_HOST = "api.typesafe.ai"
ENDPOINT_PATH = "/v1/systemone"
USER_AGENT = "jev-skill-router/0.2.0"
#: Hosts allowed to be reached over plaintext, for tests and local stubs only.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: Where the key lives when neither TYPESAFE_API_KEY nor JEV_ROUTER_KEY_FILE says otherwise.
DEFAULT_KEY_FILE = ".config/typesafe/api_key"
_KEY_NAME = "TYPESAFE_API_KEY"
#: What Claude Code exports for the plugin's ``api_key`` user-config field.
_OPTION_KEY_NAME = "CLAUDE_PLUGIN_OPTION_API_KEY"


class JevError(RuntimeError):
    """Any failure talking to the API. The hook turns this into a logged `reason`."""


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every 30x instead of following it.

    ``urlopen`` re-sends the ``Authorization`` header to whatever ``Location`` names without
    re-checking its scheme, so one 302 puts the key on the wire in cleartext. An API endpoint
    has no reason to redirect a POST, and refusing is simpler to reason about than
    re-validating each hop. ``Location`` is attacker-influenced text that ends up in the hook
    log's ``reason``, so only its scheme and host are kept.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        parts = urllib.parse.urlsplit(newurl)
        raise JevError(f"HTTP {code} redirect to {parts.scheme}://{parts.hostname}")


#: Every request goes through this opener, never the module-level ``urlopen``.
_OPENER = urllib.request.build_opener(_RefuseRedirects)


def read_api_key_file(path: Path) -> str:
    """First usable key in ``path``: a bare key on its own line, or ``TYPESAFE_API_KEY=...``.

    Both shapes exist in the wild (the cookbook exports the variable; a key file often just
    holds the value), and guessing wrong means a silent no-key skip on every prompt.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            if name.strip() == _KEY_NAME:
                return value.strip().strip("\"'")
            continue
        return line.strip("\"'")
    return ""


def resolve_api_key(env: Mapping[str, str]) -> str:
    """``TYPESAFE_API_KEY`` -> ``CLAUDE_PLUGIN_OPTION_API_KEY`` -> ``JEV_ROUTER_KEY_FILE``
    -> ``~/.config/typesafe/api_key``.

    The plugin option sits below the direct variable so a shell that exports a key for one
    command still wins over whatever the installed plugin was configured with, and above the
    key files so someone who configures the plugin never has to also plant a file. The option
    is declared ``sensitive``, which means Claude Code keeps it in secure storage and exports
    it here rather than substituting it into the hook's command line.
    """
    for name in (_KEY_NAME, _OPTION_KEY_NAME):
        direct = (env.get(name) or "").strip()
        if direct:
            return direct
    override = env.get("JEV_ROUTER_KEY_FILE")
    if override:
        return read_api_key_file(Path(override))
    home = env.get("HOME")
    if not home:
        return ""
    return read_api_key_file(Path(home) / DEFAULT_KEY_FILE)


def check_endpoint(url: str) -> None:
    """Refuse an endpoint this key must not be sent to.

    ``base_url`` comes from ``TYPESAFE_BASE_URL``, and every request carries the API key in
    an ``Authorization`` header plus the user's whole prompt in the body. Without this,
    anything able to set one environment variable on an unattended hook — a project's
    direnv, for instance — redirects both to a host of its choosing.

    Both halves are needed, and the scheme alone is not enough: ``https://attacker.example``
    is perfectly encrypted, to the attacker. So the **host** is pinned to the real API or to
    loopback, and plaintext is allowed only against loopback, which is what the tests and
    local stubs use. This matters more since the key can arrive from an installed plugin's
    configuration (``resolve_api_key``): the key is then present in every session's
    environment rather than only where someone deliberately exported it.
    """
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in LOOPBACK_HOSTS and parts.scheme in ("http", "https"):
        return
    if host != API_HOST:
        raise JevError(f"refusing endpoint host {host!r}")
    if parts.scheme != "https":
        raise JevError(f"refusing endpoint scheme {parts.scheme!r}")


class JevClient:
    """One endpoint, one method, no state beyond the key."""

    def __init__(self, api_key: str, *, base_url: str | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{ENDPOINT_PATH}"

    def ask(
        self,
        state: Mapping[str, str],
        questions: Mapping[str, dict],
        *,
        model: str,
        timeout: float,
    ) -> dict:
        if not self.api_key:
            raise JevError("no API key")
        check_endpoint(self.endpoint)
        body = json.dumps(
            {"state": state, "model": model, "questions": dict(questions)}, ensure_ascii=False
        ).encode("utf-8")
        try:
            # Built inside the try: a malformed base_url raises ValueError here, and the
            # documented contract is that everything out of this method is a JevError.
            request = urllib.request.Request(  # noqa: S310 - scheme checked above
                self.endpoint,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            with _OPENER.open(request, timeout=timeout) as handle:  # noqa: S310
                payload = json.loads(handle.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The body may carry the key back in an echoed request; only the status is kept.
            raise JevError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise JevError(type(exc).__name__) from exc
        if not isinstance(payload, dict):
            raise JevError("malformed response")
        return payload
