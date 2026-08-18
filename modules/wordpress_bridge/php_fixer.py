from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.logger import get_logger
from modules.plugin_agent.plugin_generator import invoke_claude_code
from modules.wordpress_bridge.domain import GeneratedFix

logger = get_logger(__name__)

FIXES_DIR = Path(__file__).resolve().parent / "_generated_fixes"
FIXES_DIR.mkdir(parents=True, exist_ok=True)

_CODE_BLOCK_RE = re.compile(r"```(?:php)?\s*\n(.*?)```", re.DOTALL)
_DEFAULT_TIMEOUT_SECONDS = 120.0


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (slug[:40] or "php_fix").rstrip("_")


def _extract_php_code(response_text: str) -> str:
    match = _CODE_BLOCK_RE.search(response_text)
    if match:
        return match.group(1).strip()
    # No fenced block — assume the whole response is the code (Claude
    # sometimes replies with bare PHP when asked for "only the code").
    return response_text.strip()


def _build_prompt(problem_description: str, context_snippet: str | None) -> str:
    parts = [
        "Нужен точечный PHP-фикс для темы/плагина WordPress. Опиши проблему "
        "решением в виде готового PHP-кода (функция или хук), без пояснений "
        "вокруг — ответ должен содержать ТОЛЬКО PHP-код в одном блоке "
        "```php ... ```. Не читай и не изменяй никакие файлы — просто "
        "напиши код в ответе.",
        f"Проблема: {problem_description}",
    ]
    if context_snippet:
        parts.append(f"Соответствующий существующий код/контекст:\n{context_snippet}")
    return "\n\n".join(parts)


def generate_fix(problem_description: str, context_snippet: str | None = None) -> GeneratedFix:
    """Generates a PHP fix via the Claude Code CLI (the same
    invoke_claude_code() modules.plugin_agent uses) with no file-write
    access at all — a WordPress install isn't part of this repo, so there's
    no directory it would be safe to let Claude write into directly. The
    fix is saved to disk by this function, from the CLI's text response,
    and is never applied to any live site by this code."""
    prompt = _build_prompt(problem_description, context_snippet)
    with tempfile.TemporaryDirectory(prefix="wordpress_php_fix_") as scratch_dir:
        completed = invoke_claude_code(
            prompt,
            cwd=Path(scratch_dir),
            timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
            permission_mode=None,
            allowed_tools=None,
            disallowed_tools="Bash WebFetch WebSearch Write Edit",
        )

    if completed.returncode != 0:
        raise RuntimeError(
            f"Claude Code CLI exited with code {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )

    try:
        payload = json.loads(completed.stdout)
        response_text = payload.get("result") or payload.get("response") or completed.stdout
    except (json.JSONDecodeError, TypeError):
        response_text = completed.stdout

    php_code = _extract_php_code(response_text)
    if not php_code:
        raise RuntimeError("Claude Code CLI did not return any PHP code.")

    fix = GeneratedFix(
        slug=_slugify(problem_description),
        problem_description=problem_description,
        php_code=php_code,
        created_at=datetime.now(timezone.utc),
    )
    _save_fix(fix)
    return fix


def _meta_path(filename: str) -> Path:
    return FIXES_DIR / f"{filename}.meta.json"


def _save_fix(fix: GeneratedFix) -> Path:
    php_path = FIXES_DIR / fix.filename
    php_path.write_text(fix.php_code, encoding="utf-8")
    _meta_path(fix.filename).write_text(
        json.dumps(
            {
                "problem_description": fix.problem_description,
                "created_at": fix.created_at.isoformat(),
                "reviewed": fix.reviewed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Saved generated PHP fix to %s (never applied to any live site)", php_path)
    return php_path


def list_fixes() -> list[dict[str, object]]:
    """Reads _generated_fixes/*.meta.json — this directory is the source of
    truth (no database), since a fix's whole lifecycle is just "sits on
    disk until the user reads it, then optionally deletes it"."""
    fixes: list[dict[str, object]] = []
    for meta_file in sorted(FIXES_DIR.glob("*.meta.json")):
        filename = meta_file.name.removesuffix(".meta.json")
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read metadata for generated fix %s: %s", filename, exc, exc_info=True)
            continue
        fixes.append({"filename": filename, **meta})
    return fixes


def get_fix_code(filename: str) -> str:
    php_path = FIXES_DIR / filename
    if not php_path.is_file() or php_path.parent != FIXES_DIR:
        raise ValueError(f"Неизвестное сгенерированное исправление: {filename}")
    return php_path.read_text(encoding="utf-8")


def mark_reviewed(filename: str) -> None:
    meta_path = _meta_path(filename)
    if not meta_path.is_file():
        raise ValueError(f"Неизвестное сгенерированное исправление: {filename}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["reviewed"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def discard_fix(filename: str) -> None:
    php_path = FIXES_DIR / filename
    if not php_path.is_file() or php_path.parent != FIXES_DIR:
        raise ValueError(f"Неизвестное сгенерированное исправление: {filename}")
    php_path.unlink()
    _meta_path(filename).unlink(missing_ok=True)
