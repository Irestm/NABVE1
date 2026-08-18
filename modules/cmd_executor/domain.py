from __future__ import annotations

import platform
from dataclasses import dataclass

from modules.cmd_executor.whitelist import WHITELIST


@dataclass(frozen=True)
class WhitelistedCommand:
    name: str
    argv: list[str]

    @classmethod
    def resolve(cls, name: str) -> "WhitelistedCommand":
        if name not in WHITELIST:
            raise ValueError(f"Команда «{name}» не входит в белый список.")
        entry = WHITELIST[name]
        if isinstance(entry, dict):
            system = platform.system()
            if system not in entry:
                raise ValueError(f"Команда «{name}» не входит в белый список для ОС «{system}».")
            return cls(name=name, argv=entry[system])
        return cls(name=name, argv=entry)
