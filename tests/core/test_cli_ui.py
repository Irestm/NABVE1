from __future__ import annotations

import core.cli_ui as cli_ui


def test_print_identity_panel_does_not_raise() -> None:
    cli_ui.print_identity_panel("Telegram login successful", {"Account": "@ira", "Stored in": "keyring"})


def test_print_error_panel_does_not_raise_with_and_without_hint() -> None:
    cli_ui.print_error_panel("Error", "Something broke")
    cli_ui.print_error_panel("Error", "Something broke", hint="Try running the login helper again")


def test_confirm_identity_mismatch_returns_confirm_ask_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ask(prompt, default=False, console=None):
        captured["prompt"] = prompt
        captured["default"] = default
        return True

    monkeypatch.setattr(cli_ui.Confirm, "ask", staticmethod(fake_ask))

    result = cli_ui.confirm_identity_mismatch(
        "Telegram",
        old_identity={"ID": "111", "Username": "@old"},
        new_identity={"ID": "222", "Username": "@new"},
    )

    assert result is True
    assert captured["default"] is False


def test_confirm_identity_mismatch_returns_false_on_decline(monkeypatch) -> None:
    monkeypatch.setattr(cli_ui.Confirm, "ask", staticmethod(lambda prompt, default=False, console=None: False))

    result = cli_ui.confirm_identity_mismatch(
        "Gmail", old_identity={"Email": "old@example.com"}, new_identity={"Email": "new@example.com"}
    )

    assert result is False
