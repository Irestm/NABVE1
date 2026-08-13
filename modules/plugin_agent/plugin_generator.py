from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import BASE_DIR
from core.logger import get_logger
from modules.plugin_agent import git_safety

logger = get_logger(__name__)

PLUGINS_DIR = BASE_DIR / "modules" / "plugins"
PENDING_DIR = PLUGINS_DIR / "_pending"
try:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # AI-assisted generation deliberately stays tied to BASE_DIR (see
    # git_safety.py — it rolls back anything a generation run touched
    # outside _pending/ via the real project git repo, which only makes
    # sense against a live, writable checkout). A packaged build's BASE_DIR
    # is a read-only mount; generation just isn't available there —
    # process_next_ready_candidate's caller already logs and moves on.
    logger.warning("%s is not writable; AI-assisted plugin generation is unavailable.", PENDING_DIR)

INTERFACE_PATH = "modules/plugin_agent/plugin_interface.py"
DEFAULT_TIMEOUT_SECONDS = 120


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (slug[:40] or "generated_plugin").rstrip("_")


def build_generation_prompt(gap_candidate: dict[str, Any]) -> str:
    description = gap_candidate["representative_text"]
    slug_hint = _slugify(description)
    return (
        "В проекте Jarvis нужно создать новый плагин по интерфейсу "
        f"{INTERFACE_PATH} (Protocol Plugin: атрибуты name, description, "
        "trigger_patterns: list[str], метод execute(params: dict) -> dict). "
        f"Пользователь часто просит следующее: \"{description}\". "
        "Проанализируй существующие плагины в modules/plugins/ (файлы "
        "верхнего уровня, НЕ трогай modules/plugins/_pending/) чтобы понять "
        "стиль кода и конвенции проекта, и создай новый плагин, реализующий "
        "это действие. Файл плагина должен определять на верхнем уровне "
        "модуля переменную `plugin` — экземпляр класса, реализующего "
        "протокол Plugin. Плагину категорически запрещено импортировать или "
        "иным образом использовать modules.password_manager, keyring, любые "
        "другие хранилища секретов, а также запускать произвольные "
        "shell-команды через os.system или subprocess с shell=True. "
        f"Сохрани результат ОДНИМ файлом в "
        f"modules/plugins/_pending/{slug_hint}.py. "
        "Не изменяй никакие другие существующие файлы за пределами "
        "modules/plugins/_pending/."
    )


def invoke_claude_code(
    prompt: str,
    *,
    cwd: Path = BASE_DIR,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    argv = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
        # Best-effort scoping so the CLI itself avoids touching anything but
        # the pending dir; git_safety.enforce_pending_only() is the actual
        # authority and rolls back anything that slips past this anyway.
        "--allowedTools",
        "Read Glob Grep Write(modules/plugins/_pending/**) Edit(modules/plugins/_pending/**)",
        "--disallowedTools",
        "Bash WebFetch WebSearch",
    ]
    logger.info("Invoking Claude Code CLI for plugin generation (timeout=%ss)", timeout_seconds)
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("Claude Code CLI timed out after %ss", timeout_seconds)
        raise RuntimeError(f"Claude Code CLI timed out after {timeout_seconds}s") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Claude Code CLI ('claude') not found on PATH. Install it and make sure "
            "it is reachable from the assistant process."
        ) from exc

    logger.info("Claude Code CLI exited with code %s", completed.returncode)
    if completed.stdout:
        logger.info("Claude Code CLI stdout: %s", completed.stdout[:4000])
    if completed.stderr:
        logger.info("Claude Code CLI stderr: %s", completed.stderr[:4000])
    return completed


@dataclass
class SafetyReport:
    flags: list[str] = field(default_factory=list)

    @property
    def requires_manual_review(self) -> bool:
        return bool(self.flags)


@dataclass
class GenerationResult:
    success: bool
    plugin_path: Path | None = None
    plugin_name: str | None = None
    safety_report: SafetyReport | None = None
    error: str | None = None
    rolled_back_files: list[str] = field(default_factory=list)


_DANGEROUS_MODULES = {"keyring", "modules.password_manager", "ctypes"}
_NETWORK_MODULES = {"requests", "urllib", "urllib.request", "httpx", "http.client", "socket"}
_DANGEROUS_CALLS = {"os.system", "os.popen", "eval", "exec"}
_SUBPROCESS_CALLS = {"subprocess.run", "subprocess.popen", "subprocess.call", "subprocess.check_output"}


def _qualified_call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        owner = func.value.id if isinstance(func.value, ast.Name) else None
        return f"{owner}.{func.attr}" if owner else func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def analyze_plugin_safety(path: Path) -> SafetyReport:
    source = path.read_text(encoding="utf-8")
    flags: list[str] = []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return SafetyReport(flags=[f"Код не парсится (SyntaxError: {exc})"])

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
            )
            for name in names:
                if not name:
                    continue
                if any(name == d or name.startswith(d + ".") for d in _DANGEROUS_MODULES):
                    if "keyring" in name or "password_manager" in name:
                        flags.append(f"Импорт запрещённого модуля: {name}")
                    else:
                        flags.append(f"Импорт потенциально опасного модуля: {name}")
                if any(name == n or name.startswith(n + ".") for n in _NETWORK_MODULES):
                    flags.append(f"Сетевой модуль: {name}")

        if isinstance(node, ast.Call):
            qualified = (_qualified_call_name(node) or "").lower()
            if qualified in _DANGEROUS_CALLS:
                flags.append(f"Опасный вызов: {qualified}")

            if qualified in _SUBPROCESS_CALLS:
                shell_true = any(
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in node.keywords
                )
                if shell_true:
                    flags.append(f"Опасный вызов: {qualified}(shell=True)")
                if node.args and not isinstance(node.args[0], (ast.List, ast.Tuple, ast.Constant)):
                    flags.append(f"{qualified} вызывается с непроверяемыми аргументами")

    for match in re.finditer(r"https?://[\w./-]+", source):
        flags.append(f"Обращение к сети: {match.group(0)}")

    if re.search(r"password_manager|keyring", source) and not any(
        "password_manager" in f or "keyring" in f for f in flags
    ):
        flags.append("Упоминание password_manager/keyring в коде")

    return SafetyReport(flags=sorted(set(flags)))


def generate_plugin_for_candidate(
    candidate: dict[str, Any], *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> GenerationResult:
    try:
        git_safety.snapshot(label=f"candidate-{candidate['id']}")
    except git_safety.GitSafetyError as exc:
        return GenerationResult(success=False, error=str(exc))

    prompt = build_generation_prompt(candidate)
    try:
        completed = invoke_claude_code(prompt, timeout_seconds=timeout_seconds)
    except RuntimeError as exc:
        return GenerationResult(success=False, error=str(exc))

    diff_result = git_safety.enforce_pending_only()

    if completed.returncode != 0:
        return GenerationResult(
            success=False,
            error=f"Claude Code CLI exited with code {completed.returncode}: {completed.stderr[:2000]}",
            rolled_back_files=diff_result["rolled_back"],
        )

    new_files = [
        BASE_DIR / rel_path for rel_path in diff_result["kept"] if rel_path.endswith(".py")
    ]
    if not new_files:
        return GenerationResult(
            success=False,
            error="Claude Code CLI did not produce a plugin file in modules/plugins/_pending/.",
            rolled_back_files=diff_result["rolled_back"],
        )

    plugin_path = new_files[0]
    safety_report = analyze_plugin_safety(plugin_path)
    return GenerationResult(
        success=True,
        plugin_path=plugin_path,
        plugin_name=plugin_path.stem,
        safety_report=safety_report,
        rolled_back_files=diff_result["rolled_back"],
    )
