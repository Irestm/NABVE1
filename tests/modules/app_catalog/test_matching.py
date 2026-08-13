from __future__ import annotations

from modules.app_catalog.domain import InstalledApp
from modules.app_catalog.matching import shortlist_candidates, transliterate


def _apps(*names: str) -> list[InstalledApp]:
    return [InstalledApp(display_name=name, launch_target=name.lower(), source="desktop") for name in names]


def test_transliterate_maps_cyrillic_to_latin_phonetics() -> None:
    assert transliterate("дед селс") == "ded sels"


def test_transliterate_is_case_insensitive() -> None:
    assert transliterate("ДЕД СЕЛС") == "ded sels"


def test_transliterate_leaves_latin_text_untouched() -> None:
    assert transliterate("dead cells") == "dead cells"


def test_short_lists_are_returned_as_is() -> None:
    apps = _apps("A", "B", "C")
    assert shortlist_candidates("anything", apps, limit=15) == apps


def test_cyrillic_phonetic_query_surfaces_the_right_latin_app() -> None:
    # This is the motivating scenario: STT hears the Russian pronunciation
    # of an English game title, and plain character similarity against the
    # real (Latin) name would score ~0 — see test_transliterate_* above.
    apps = _apps(*[f"Filler App {i}" for i in range(20)], "Dead Cells")

    shortlisted = shortlist_candidates("дед селс", apps, limit=5)

    assert any(app.display_name == "Dead Cells" for app in shortlisted)
    assert len(shortlisted) == 5


def test_close_spelling_match_is_shortlisted_without_transliteration() -> None:
    apps = _apps(*[f"Filler App {i}" for i in range(20)], "Stardew Valley")

    shortlisted = shortlist_candidates("stardew valey", apps, limit=5)

    assert any(app.display_name == "Stardew Valley" for app in shortlisted)


def test_falls_back_to_untrimmed_slice_when_nothing_scores_well() -> None:
    # Every candidate is equally (un)related to the query - trusting a
    # near-zero-confidence ranking here would risk dropping the right
    # answer just as easily as keeping it, so the safer behavior is not to
    # rank at all.
    apps = _apps(*[f"Xq{i}zzt" for i in range(20)])

    shortlisted = shortlist_candidates("совершенно другой запрос", apps, limit=5)

    assert len(shortlisted) == 5
