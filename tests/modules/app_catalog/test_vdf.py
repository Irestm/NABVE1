from __future__ import annotations

import pytest

from modules.app_catalog.vdf import find_all_values, find_value, parse_vdf


def test_parses_flat_block() -> None:
    text = """
    "AppState"
    {
        "appid"		"12345"
        "name"		"Dead Cells"
    }
    """
    data = parse_vdf(text)
    assert data == {"AppState": {"appid": "12345", "name": "Dead Cells"}}


def test_parses_nested_blocks_with_numeric_index_keys() -> None:
    text = """
    "libraryfolders"
    {
        "0"
        {
            "path"		"/home/user/.steam/steam"
        }
        "1"
        {
            "path"		"/mnt/games/SteamLibrary"
        }
    }
    """
    data = parse_vdf(text)
    assert find_all_values(data, "path") == [
        "/home/user/.steam/steam",
        "/mnt/games/SteamLibrary",
    ]


def test_find_value_returns_first_match_or_none() -> None:
    data = {"AppState": {"appid": "1", "name": "Game"}}
    assert find_value(data, "name") == "Game"
    assert find_value(data, "missing") is None


def test_handles_escaped_quotes_and_backslashes() -> None:
    text = r"""
    "AppState"
    {
        "installdir"	"C:\\Program Files\\Game"
        "name"		"Say \"hi\""
    }
    """
    data = parse_vdf(text)
    assert data["AppState"]["installdir"] == r"C:\Program Files\Game"
    assert data["AppState"]["name"] == 'Say "hi"'


def test_empty_text_returns_empty_dict() -> None:
    assert parse_vdf("") == {}


def test_key_without_value_raises() -> None:
    with pytest.raises(ValueError):
        parse_vdf('"AppState" { "appid" }')


def test_truncated_nested_block_raises_instead_of_returning_partial_data() -> None:
    # A file cut off mid-write (e.g. Steam killed while updating
    # appmanifest_*.acf) must not silently succeed with partial/mis-scoped
    # data - the whole point of raising ValueError here is that callers
    # (modules/app_catalog/steam.py) already know to catch it and skip the
    # file entirely.
    with pytest.raises(ValueError):
        parse_vdf('"AppState" { "appid" "1" "name" "Dead Cells"')


def test_truncated_top_level_bare_document_does_not_raise() -> None:
    # A bare top-level document (no enclosing root "{ }") has no closing
    # brace to miss in the first place - running out of tokens here is just
    # the normal end of input, not truncation.
    assert parse_vdf('"key" "value"') == {"key": "value"}
