from __future__ import annotations

from modules.user_profile.communication_styles import (
    COMMUNICATION_STYLES,
    DEFAULT_STYLE_KEY,
    MAX_SELECTED_STYLES,
    combine_styles,
    get_style,
    parse_style_keys,
)


def test_unknown_key_falls_back_to_default() -> None:
    style = get_style("does-not-exist")
    assert style.key == DEFAULT_STYLE_KEY


def test_none_key_falls_back_to_default() -> None:
    style = get_style(None)
    assert style.key == DEFAULT_STYLE_KEY


def test_known_key_returns_matching_style() -> None:
    style = get_style("aggressive")
    assert style.label == "Агрессивно"
    assert style.prosody_rate > 1.0


def test_calm_style_is_slower_than_neutral() -> None:
    calm = get_style("calm")
    neutral = get_style(DEFAULT_STYLE_KEY)
    assert calm.prosody_rate < neutral.prosody_rate


def test_style_keys_are_unique() -> None:
    keys = [style.key for style in COMMUNICATION_STYLES]
    assert len(keys) == len(set(keys))


def test_at_least_eight_styles_are_offered() -> None:
    assert len(COMMUNICATION_STYLES) >= 8


def test_philosophical_style_exists() -> None:
    style = get_style("philosophical")
    assert style.label == "Философски"


# --- parse_style_keys ---------------------------------------------------


def test_parse_style_keys_none_returns_default() -> None:
    assert parse_style_keys(None) == [DEFAULT_STYLE_KEY]


def test_parse_style_keys_empty_returns_default() -> None:
    assert parse_style_keys("") == [DEFAULT_STYLE_KEY]


def test_parse_style_keys_single_legacy_value_still_works() -> None:
    # Format used before trait-mixing existed: one bare key, no comma.
    assert parse_style_keys("aggressive") == ["aggressive"]


def test_parse_style_keys_splits_and_dedupes() -> None:
    assert parse_style_keys("aggressive,humorous,aggressive") == ["aggressive", "humorous"]


def test_parse_style_keys_drops_unknown_keys() -> None:
    assert parse_style_keys("aggressive,bogus,humorous") == ["aggressive", "humorous"]


def test_parse_style_keys_caps_at_max_selected() -> None:
    raw = "aggressive,humorous,formal,rude,friendly"
    result = parse_style_keys(raw)
    assert len(result) == MAX_SELECTED_STYLES
    assert result == ["aggressive", "humorous", "formal"]


def test_parse_style_keys_all_unknown_returns_default() -> None:
    assert parse_style_keys("bogus,also-bogus") == [DEFAULT_STYLE_KEY]


# --- combine_styles ------------------------------------------------------


def test_combine_single_style_returns_it_unchanged() -> None:
    combined = combine_styles(["aggressive"])
    assert combined == get_style("aggressive")


def test_combine_multiple_styles_merges_label_and_fragment() -> None:
    combined = combine_styles(["aggressive", "humorous"])
    assert combined.label == "Агрессивно + С юмором"
    assert get_style("aggressive").prompt_fragment in combined.prompt_fragment
    assert get_style("humorous").prompt_fragment in combined.prompt_fragment


def test_combine_multiple_styles_averages_prosody_rate() -> None:
    combined = combine_styles(["aggressive", "humorous"])
    expected = (get_style("aggressive").prosody_rate + get_style("humorous").prosody_rate) / 2
    assert combined.prosody_rate == expected


def test_combine_empty_list_falls_back_to_default() -> None:
    combined = combine_styles([])
    assert combined.key == DEFAULT_STYLE_KEY
