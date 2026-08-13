from __future__ import annotations

import ast
import importlib.util
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import BASE_DIR
from core.dispatcher import CommandDispatcher
from core.logger import get_logger
from modules.plugin_agent.plugin_interface import validate_plugin

logger = get_logger(__name__)

PLUGINS_DIR = BASE_DIR / "modules" / "plugins"
PENDING_DIR = PLUGINS_DIR / "_pending"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
PENDING_DIR.mkdir(parents=True, exist_ok=True)

# Plugins are never allowed direct access to secrets storage, no matter what
# an AI-generated file claims to do. Enforced here (not just at review time)
# so a plugin approved without careful reading still can't load.
_FORBIDDEN_IMPORTS = ("keyring", "modules.password_manager")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def find_forbidden_import(source: str) -> str | None:
    """Not underscore-prefixed: also re-run inside the sandboxed subprocess
    (see modules/plugin_agent/sandbox_runner.py's _main) as a defense-in-
    depth re-check right before a plugin actually executes, not just at
    load time."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in _FORBIDDEN_IMPORTS:
                    if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                        return alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for forbidden in _FORBIDDEN_IMPORTS:
                if node.module == forbidden or node.module.startswith(forbidden + "."):
                    return node.module
    return None


@dataclass
class LoadedPlugin:
    name: str
    description: str
    trigger_patterns: list[str]
    instance: Any
    module_name: str
    file_path: Path


class PluginRegistry:
    def __init__(self, dispatcher: CommandDispatcher) -> None:
        self._dispatcher = dispatcher
        self._plugins: dict[str, LoadedPlugin] = {}
        self._trigger_index: dict[str, str] = {}
        self._lock = threading.Lock()

    @property
    def plugins(self) -> dict[str, LoadedPlugin]:
        with self._lock:
            return dict(self._plugins)

    @staticmethod
    def _make_handler(file_path: Path):
        async def _handler(params: dict[str, Any]) -> dict[str, Any]:
            # Imported here, not at module level: sandbox_runner.py is also run
            # directly via `python -m modules.plugin_agent.sandbox_runner` inside
            # the sandboxed subprocess this spawns. An eager top-level import here
            # would make this module transitively import sandbox_runner under its
            # normal dotted name before runpy's -m machinery executes it as
            # __main__, giving Python two module objects for the same file and a
            # "found in sys.modules ... prior to execution" warning.
            #
            # Runs in a fresh subprocess, not in-process — see sandbox_runner.py's
            # own docstring for why: approval (handlers.py's approve/reject flow)
            # isn't the same as trust, and the subprocess boundary limits what a
            # buggy or overreaching plugin can do well beyond the forbidden-import
            # check alone.
            from modules.plugin_agent import sandbox_runner

            return await sandbox_runner.run_in_sandbox(file_path, params)

        return _handler

    def load_file(self, path: Path) -> LoadedPlugin | None:
        if path.parent != PLUGINS_DIR or path.suffix != ".py" or path.name.startswith("_"):
            return None

        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Could not read plugin file %s: %s", path, exc)
            return None

        forbidden = find_forbidden_import(source)
        if forbidden:
            logger.error(
                "Refusing to load plugin '%s': forbidden import '%s' (plugins may "
                "never access password_manager/keyring directly)",
                path.name,
                forbidden,
            )
            return None

        module_name = f"modules.plugins._loaded.{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not build import spec for {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            logger.exception("Failed to import plugin '%s'", path.name)
            sys.modules.pop(module_name, None)
            return None

        instance = getattr(module, "plugin", None)
        if instance is None:
            logger.error(
                "Plugin file '%s' does not define a module-level 'plugin' instance", path.name
            )
            sys.modules.pop(module_name, None)
            return None

        errors = validate_plugin(instance)
        if errors:
            logger.error("Plugin '%s' failed interface validation: %s", path.name, errors)
            sys.modules.pop(module_name, None)
            return None

        return LoadedPlugin(
            name=instance.name,
            description=instance.description,
            trigger_patterns=list(instance.trigger_patterns),
            instance=instance,
            module_name=module_name,
            file_path=path,
        )

    def register(self, loaded: LoadedPlugin) -> None:
        with self._lock:
            if loaded.name in self._plugins:
                self._unlock_unregister(loaded.name)
            self._dispatcher.unregister(loaded.name)
            self._dispatcher.register(
                loaded.name,
                self._make_handler(loaded.file_path),
                dangerous=False,
                description=loaded.description,
            )
            self._plugins[loaded.name] = loaded
            for pattern in loaded.trigger_patterns:
                self._trigger_index[_normalize(pattern)] = loaded.name
        logger.info(
            "Registered plugin '%s' (%d trigger patterns) from %s",
            loaded.name,
            len(loaded.trigger_patterns),
            loaded.file_path.name,
        )

    def _unlock_unregister(self, name: str) -> None:
        # Caller already holds self._lock.
        loaded = self._plugins.pop(name, None)
        self._dispatcher.unregister(name)
        if loaded:
            for pattern in loaded.trigger_patterns:
                if self._trigger_index.get(_normalize(pattern)) == name:
                    del self._trigger_index[_normalize(pattern)]
            sys.modules.pop(loaded.module_name, None)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._unlock_unregister(name)

    def unregister_by_path(self, path: Path) -> None:
        with self._lock:
            name = next(
                (n for n, p in self._plugins.items() if p.file_path == path), None
            )
        if name:
            self.unregister(name)
            logger.info("Unregistered plugin '%s' after file removal: %s", name, path.name)

    def load_all(self) -> None:
        for path in sorted(PLUGINS_DIR.glob("*.py")):
            loaded = self.load_file(path)
            if loaded:
                self.register(loaded)

    def reload_file(self, path: Path) -> None:
        loaded = self.load_file(path)
        if loaded:
            self.register(loaded)

    def match_command(self, text: str) -> str | None:
        normalized = _normalize(text)
        if not normalized:
            return None
        with self._lock:
            if normalized in self._trigger_index:
                return self._trigger_index[normalized]
            for pattern, name in self._trigger_index.items():
                if pattern and pattern in normalized:
                    return name
        return None


_registry: PluginRegistry | None = None


def get_registry() -> PluginRegistry:
    if _registry is None:
        raise RuntimeError("Plugin registry has not been initialized; call init_plugin_loader() first")
    return _registry


def init_plugin_loader(dispatcher: CommandDispatcher) -> PluginRegistry:
    global _registry
    _registry = PluginRegistry(dispatcher)
    _registry.load_all()
    return _registry


def match_command(text: str) -> str | None:
    if _registry is None:
        return None
    return _registry.match_command(text)


def start_hot_reload() -> Any | None:
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        logger.warning(
            "watchdog is not installed; plugin hot-reload disabled. "
            "Install it with: pip install watchdog"
        )
        return None

    registry = get_registry()

    class _Handler(FileSystemEventHandler):
        def on_created(self, event: FileSystemEvent) -> None:
            self._maybe_reload(event)

        def on_modified(self, event: FileSystemEvent) -> None:
            self._maybe_reload(event)

        def on_moved(self, event: FileSystemEvent) -> None:
            self._maybe_reload(event)

        def on_deleted(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.parent == PLUGINS_DIR and path.suffix == ".py":
                registry.unregister_by_path(path)

        def _maybe_reload(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.parent != PLUGINS_DIR or path.suffix != ".py" or path.name.startswith("_"):
                return
            # Editors write files in bursts (truncate, then write content);
            # a short debounce avoids importing a half-written file.
            time.sleep(0.15)
            registry.reload_file(path)

    observer = Observer()
    observer.schedule(_Handler(), str(PLUGINS_DIR), recursive=False)
    observer.daemon = True
    observer.start()
    logger.info("Plugin hot-reload watcher started on %s", PLUGINS_DIR)
    return observer
