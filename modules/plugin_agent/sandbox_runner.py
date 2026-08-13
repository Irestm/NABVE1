from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.config import BASE_DIR
from core.logger import get_logger

logger = get_logger(__name__)

# Wall-clock ceiling for one plugin execute() call. Plugins in this project
# are meant to be quick, synchronous helpers (e.g. "what time is it") — this
# is generous headroom for that, not a budget for genuinely long-running
# work, which doesn't belong in a voice-triggered plugin anyway.
_TIMEOUT_SECONDS = 15.0

# Allowlist, not a blocklist: this project keeps adding new secret-bearing
# env vars as features grow (GROQ_API_KEY, ASSISTANT_TELEGRAM_API_HASH,
# ASSISTANT_GMAIL_CLIENT_SECRET, ASSISTANT_API_TOKEN, ...), and a blocklist
# would silently miss whichever one gets added next. Only what's actually
# needed to run a plain Python interpreter and its stdlib is passed through
# to the sandboxed process.
_ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "PYTHONIOENCODING",
)


class PluginSandboxError(RuntimeError):
    pass


def _sandboxed_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    # Needed for `python -m modules.plugin_agent.sandbox_runner` to resolve
    # the `modules`/`core` packages at all: the subprocess runs with cwd set
    # to a throwaway temp directory (see run_in_sandbox), not the project
    # root, so it isn't on sys.path by default the way it is for the main
    # process.
    env["PYTHONPATH"] = str(BASE_DIR)
    return env


async def run_in_sandbox(plugin_path: Path, params: dict[str, Any]) -> dict[str, Any]:
    """Runs `plugin_path`'s `execute(params)` in a fresh subprocess rather
    than in-process (see modules/plugin_agent/plugin_loader.py's
    PluginRegistry._make_handler, the only caller): a wall-clock timeout, a
    throwaway working directory, and an env-var allowlist stand in for the
    2-item forbidden-import check that was previously the only runtime
    restriction on what AI-generated plugin code (already human-approved —
    see modules/plugin_agent/handlers.py's approve/reject flow — but still
    arbitrary Python) can do once it actually runs. The plugin file is
    re-imported fresh inside the subprocess (see _main below, and its own
    forbidden-import re-check) — the metadata-only import
    PluginRegistry.load_file does in the main process is unaffected.

    Raises PluginSandboxError on timeout, a non-zero exit, unparseable
    output, or a reported execute() failure — the caller's own try/except
    (core/dispatcher.py's CommandDispatcher._execute) turns any of these
    into an ordinary CommandStatus.FAILED response, same as an in-process
    plugin exception used to before this feature existed."""
    with tempfile.TemporaryDirectory(prefix="nabve-plugin-sandbox-") as work_dir:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "modules.plugin_agent.sandbox_runner",
            str(plugin_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env=_sandboxed_env(),
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(params).encode("utf-8")), timeout=_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise PluginSandboxError(
                f"Plugin '{plugin_path.name}' timed out after {_TIMEOUT_SECONDS:.0f}s"
            ) from exc

    # _main() below always exits 1 on any execute()/import failure, but
    # still writes a structured {"ok": false, "error": "..."} payload to
    # stdout first — checking that JSON before the exit code means a
    # reported failure (a forbidden import, execute() raising, ...) surfaces
    # its real reason instead of a generic "crashed" message. A non-zero
    # exit with no parseable payload at all (a genuine crash before _main
    # could even write anything) still falls through to that generic error.
    payload: dict[str, Any] | None = None
    if stdout:
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError:
            payload = None

    if payload is not None and not payload.get("ok"):
        raise PluginSandboxError(payload.get("error") or f"Plugin '{plugin_path.name}' failed")

    if process.returncode != 0 or payload is None:
        logger.error(
            "Sandboxed plugin '%s' exited with code %s: %s",
            plugin_path.name,
            process.returncode,
            stderr.decode("utf-8", errors="replace").strip(),
        )
        raise PluginSandboxError(f"Plugin '{plugin_path.name}' crashed (exit code {process.returncode})")

    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _main() -> None:
    """Entry point run inside the sandboxed subprocess (see
    run_in_sandbox above) — never imported/called directly by anything else
    in this project. Talks JSON over stdin/stdout only; anything logged
    goes to stderr so it can't be mistaken for the result payload."""
    from modules.plugin_agent.plugin_loader import find_forbidden_import

    plugin_path = Path(sys.argv[1])
    raw_params = sys.stdin.read()

    try:
        params = json.loads(raw_params) if raw_params.strip() else {}

        source = plugin_path.read_text(encoding="utf-8")
        # Defense in depth: PluginRegistry.load_file already ran this same
        # check before this plugin was ever registered, but that happened
        # against the file as it was at load/hot-reload time — re-checking
        # here closes the gap where the file changes on disk after that
        # (e.g. hot-reload disabled because `watchdog` isn't installed)
        # without ever being re-validated before running again.
        forbidden = find_forbidden_import(source)
        if forbidden:
            raise ImportError(f"forbidden import '{forbidden}' (plugins may never access secrets storage)")

        import importlib.util

        spec = importlib.util.spec_from_file_location("_sandboxed_plugin", plugin_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not build import spec for {plugin_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        instance = getattr(module, "plugin", None)
        if instance is None:
            raise AttributeError("Plugin file does not define a module-level 'plugin' instance")

        result = instance.execute(params)
        sys.stdout.write(json.dumps({"ok": True, "result": result}))
    except Exception as exc:  # noqa: BLE001 - reported to the parent process, not swallowed
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    _main()
