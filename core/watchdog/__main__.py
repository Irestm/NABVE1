from __future__ import annotations

from core.watchdog.supervisor import Supervisor


def main() -> None:
    Supervisor().run()


if __name__ == "__main__":
    main()
