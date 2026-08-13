from __future__ import annotations

import subprocess
from pathlib import Path

from core.config import BASE_DIR
from core.logger import get_logger

logger = get_logger(__name__)

PENDING_PREFIX = "modules/plugins/_pending/"


class GitSafetyError(Exception):
    pass


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        check=check,
    )


def is_git_repo() -> bool:
    result = _run_git("rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def ensure_git_repo() -> None:
    if is_git_repo():
        return
    logger.info(
        "No git repository found at %s; initializing one so AI-generated plugin "
        "code can be sandboxed and rolled back if it touches unrelated files",
        BASE_DIR,
    )
    init_result = _run_git("init", check=False)
    if init_result.returncode != 0:
        raise GitSafetyError(f"git init failed: {init_result.stderr}")
    _run_git("add", "-A", check=False)
    commit_result = _run_git(
        "commit",
        "--allow-empty",
        "-m",
        "plugin_agent: baseline snapshot before first AI-assisted plugin generation",
        check=False,
    )
    if commit_result.returncode != 0 and "nothing to commit" not in commit_result.stdout:
        raise GitSafetyError(f"git commit failed: {commit_result.stderr}")


def snapshot(label: str) -> str:
    ensure_git_repo()
    status = _run_git("status", "--porcelain", check=False)
    if status.stdout.strip():
        _run_git("add", "-A", check=False)
        _run_git(
            "commit",
            "-m",
            f"plugin_agent: pre-generation snapshot ({label})",
            check=False,
        )
    head = _run_git("rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        raise GitSafetyError(f"Could not resolve HEAD after snapshot: {head.stderr}")
    return head.stdout.strip()


def enforce_pending_only() -> dict[str, list[str]]:
    """Roll back any change Claude Code made outside modules/plugins/_pending/.

    Runs immediately after invoking the CLI. Anything it wrote or modified
    inside the pending dir is left alone; everything else is reverted
    (untracked files deleted, tracked files checked out back to the
    pre-generation snapshot) and logged.
    """
    result = _run_git("status", "--porcelain", "-uall", check=False)
    kept: list[str] = []
    rolled_back: list[str] = []

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ")[-1].strip()

        if path.startswith(PENDING_PREFIX):
            kept.append(path)
            continue

        status_code = line[:2]
        if status_code.strip() == "??":
            target = BASE_DIR / path
            if target.is_file():
                target.unlink(missing_ok=True)
            elif target.is_dir():
                _run_git("clean", "-fd", "--", path, check=False)
        else:
            _run_git("checkout", "--", path, check=False)
        rolled_back.append(path)

    if rolled_back:
        logger.warning(
            "Claude Code CLI touched files outside modules/plugins/_pending/; rolled back: %s",
            rolled_back,
        )
    if kept:
        logger.info("Kept generated file(s) in _pending: %s", kept)

    return {"kept": kept, "rolled_back": rolled_back}


def commit_enabled_plugin(path: Path) -> None:
    if not is_git_repo():
        return
    try:
        rel = path.relative_to(BASE_DIR)
    except ValueError:
        return
    _run_git("add", str(rel), check=False)
    _run_git("commit", "-m", f"plugin_agent: enable plugin {rel.name}", check=False)
