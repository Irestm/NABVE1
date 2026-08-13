from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

# One shared Console rather than one per call — rich detects terminal
# width/color support once and reuses it; these are all short-lived,
# one-shot interactive scripts (modules/telegram/login.py,
# modules/gmail/login.py), never imported by the running server, so a
# single module-level instance is fine.
_console = Console()


def print_identity_panel(title: str, fields: dict[str, str]) -> None:
    """A clean bordered success panel for a one-time login helper (see
    modules/telegram/login.py, modules/gmail/login.py) — shows which
    account just got authorized and where the credential ended up, so the
    user can visually confirm it's the right one before the app starts
    using it, rather than a bare 'login successful' line."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    for label, value in fields.items():
        table.add_row(f"{label}:", value)
    _console.print(Panel(table, title=title, border_style="green"))


def confirm_identity_mismatch(
    source_label: str, old_identity: dict[str, str], new_identity: dict[str, str]
) -> bool:
    """Shown when a login helper finds a credential already stored for a
    DIFFERENT account than the one just authenticated (see
    modules/telegram/login.py, modules/gmail/login.py — both compare a
    stable identifier, e.g. a numeric user id or an email address, before
    ever calling this). Renders an old-vs-new comparison table, one row
    per field present in either identity, then asks for explicit
    confirmation. Returns True only if the user explicitly confirms
    overwriting — the caller must not touch keyring before this returns
    True, and must leave the existing credential untouched on False."""
    table = Table(title=f"{source_label}: сохранённый аккаунт отличается", border_style="red")
    table.add_column("Поле", style="bold")
    table.add_column("Сейчас сохранено", style="yellow")
    table.add_column("Новый аккаунт", style="cyan")
    # dict.fromkeys(...) here is just "union of both dicts' keys, in a
    # stable first-seen order" — the values themselves are irrelevant and
    # immediately overwritten by None below, only the key order matters.
    for field in dict.fromkeys([*old_identity, *new_identity]):
        table.add_row(field, old_identity.get(field, "—"), new_identity.get(field, "—"))
    _console.print(table)
    return Confirm.ask(
        "Заменить сохранённые данные на новый аккаунт?", default=False, console=_console
    )


def print_error_panel(title: str, message: str, hint: str | None = None) -> None:
    """Replaces a bare raised exception/traceback in a one-time login
    helper with a clear, actionable final message before the script exits
    non-zero (see modules/telegram/login.py, modules/gmail/login.py)."""
    body = message if not hint else f"{message}\n\n[dim]{hint}[/dim]"
    _console.print(Panel(body, title=title, border_style="red"))
