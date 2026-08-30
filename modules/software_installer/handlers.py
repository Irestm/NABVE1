from __future__ import annotations

import asyncio
from typing import Any

from core.dispatcher import CommandDispatcher
from modules.software_installer import installer, package_map
from modules.software_installer.screen_fallback_installer import (
    InstallerButtonNotFoundError,
    UnsafeInstallerContextError,
    click_installer_button,
)

_MANUAL_HINT = (
    "Запусти установщик вручную и скажи «нажми далее» / «нажми установить» — помогу пройти мастер."
)


async def _handle_software_install(params: dict[str, Any]) -> dict[str, Any]:
    app = (params.get("app") or "").strip()
    if not app:
        raise ValueError("Не указано, какую программу установить.")

    if package_map.resolve(app) is None:
        return {"app": app, "known": False, "message": f"Не знаю, как поставить «{app}». {_MANUAL_HINT}"}

    plan = await asyncio.to_thread(installer.plan_install, app)
    if plan is None:
        return {
            "app": app,
            "known": True,
            "message": (
                f"«{app}» знаю, но на этой системе нет подходящего пакетного менеджера "
                f"(нужен apt/dnf/pacman, flatpak, snap или winget). {_MANUAL_HINT}"
            ),
        }

    installer.start_background_install(plan)
    return {
        "app": plan.app,
        "known": True,
        "backend": plan.backend,
        "message": f"Устанавливаю «{plan.app}» через {plan.backend} в фоне — скажу, когда закончу.",
    }


async def _handle_installer_click_button(params: dict[str, Any]) -> dict[str, Any]:
    button = (params.get("button") or "next").strip().lower()
    try:
        message = await asyncio.to_thread(click_installer_button, button)
    except (InstallerButtonNotFoundError, UnsafeInstallerContextError) as exc:
        raise RuntimeError(str(exc)) from exc
    return {"button": button, "message": message}


def register_commands(dispatcher: CommandDispatcher) -> None:
    dispatcher.register(
        "software_install",
        _handle_software_install,
        dangerous=False,
        description=(
            "Установить распространённую программу по имени (app) через пакетный менеджер системы "
            "(apt/dnf/pacman/flatpak/snap/winget). Установка идёт в фоне с голосовым отчётом."
        ),
    )
    dispatcher.register(
        "installer_click_button",
        _handle_installer_click_button,
        dangerous=False,
        description=(
            "Нажать кнопку в видимом окне стороннего установщика по её типу "
            "(button: next/install/finish/accept) — распознавание кнопки по картинке."
        ),
    )
