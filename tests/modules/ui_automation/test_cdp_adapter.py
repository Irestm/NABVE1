from __future__ import annotations

import asyncio

from modules.ui_automation.cdp_adapter import (
    ChromeCdpElementInspector,
    _strip_title_suffix,
    normalize_role,
    to_absolute_bbox,
)

# --- to_absolute_bbox --------------------------------------------------


def test_to_absolute_bbox_device_pixel_ratio_one_is_a_plain_offset() -> None:
    bbox = to_absolute_bbox(
        window_left=100,
        window_top=50,
        chrome_offset_x=0,
        chrome_offset_y=80,
        device_pixel_ratio=1.0,
        el_x=20,
        el_y=30,
        el_width=40,
        el_height=10,
    )
    assert bbox == (120, 160, 40, 10)


def test_to_absolute_bbox_applies_device_pixel_ratio() -> None:
    # Regression: getBoundingClientRect() is CSS pixels, CDP window bounds
    # are physical pixels — on a HiDPI display (ratio != 1) every offset
    # and size below the window's own origin must be scaled, or clicks
    # land at the wrong spot by exactly that factor.
    bbox = to_absolute_bbox(
        window_left=0,
        window_top=0,
        chrome_offset_x=0,
        chrome_offset_y=0,
        device_pixel_ratio=2.0,
        el_x=10,
        el_y=20,
        el_width=30,
        el_height=40,
    )
    assert bbox == (20, 40, 60, 80)


def test_to_absolute_bbox_scales_chrome_offset_too_at_1_5x() -> None:
    bbox = to_absolute_bbox(
        window_left=200,
        window_top=100,
        chrome_offset_x=0,
        chrome_offset_y=80,
        device_pixel_ratio=1.5,
        el_x=0,
        el_y=0,
        el_width=10,
        el_height=10,
    )
    # x: 200 + 1.5*(0+0) = 200; y: 100 + 1.5*(80+0) = 220
    assert bbox == (200, 220, 15, 15)


def test_to_absolute_bbox_rounds_to_int() -> None:
    bbox = to_absolute_bbox(
        window_left=0,
        window_top=0,
        chrome_offset_x=0,
        chrome_offset_y=0,
        device_pixel_ratio=1.25,
        el_x=1,
        el_y=1,
        el_width=1,
        el_height=1,
    )
    assert all(isinstance(v, int) for v in bbox)


# --- normalize_role ------------------------------------------------------


def test_normalize_role_aria_role_wins_over_tag() -> None:
    assert normalize_role("div", "", "button") == "push button"
    assert normalize_role("span", "", "tab") == "page tab"


def test_normalize_role_anchor_is_link() -> None:
    assert normalize_role("a", "", None) == "link"


def test_normalize_role_select_is_combo_box() -> None:
    assert normalize_role("select", "", None) == "combo box"


def test_normalize_role_textarea_is_entry() -> None:
    assert normalize_role("textarea", "", None) == "entry"


def test_normalize_role_input_checkbox_and_radio() -> None:
    assert normalize_role("input", "checkbox", None) == "check box"
    assert normalize_role("input", "radio", None) == "radio button"


def test_normalize_role_input_text_defaults_to_entry() -> None:
    assert normalize_role("input", "text", None) == "entry"
    assert normalize_role("input", "", None) == "entry"


def test_normalize_role_button_and_unknown_default_to_push_button() -> None:
    assert normalize_role("button", "", None) == "push button"
    assert normalize_role("div", "", None) == "push button"


# --- _strip_title_suffix ---------------------------------------------------


def test_strip_title_suffix_removes_known_chrome_suffix() -> None:
    assert _strip_title_suffix("YouTube - Google Chrome") == "YouTube"


def test_strip_title_suffix_leaves_unrelated_titles_unchanged() -> None:
    assert _strip_title_suffix("PyCharm — assistant") == "PyCharm — assistant"


# --- _find_page ------------------------------------------------------------


class _FakePage:
    def __init__(self, title: str) -> None:
        self._title = title

    async def title(self) -> str:
        return self._title


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages


class _FakeBrowser:
    def __init__(self, contexts: list[_FakeContext]) -> None:
        self.contexts = contexts


def test_find_page_matches_exact_title() -> None:
    browser = _FakeBrowser([_FakeContext([_FakePage("YouTube"), _FakePage("Gmail")])])

    page = asyncio.run(ChromeCdpElementInspector._find_page(browser, "Gmail"))

    assert page is not None
    assert asyncio.run(page.title()) == "Gmail"


def test_find_page_skips_empty_titled_pages_instead_of_matching_everything() -> None:
    # Regression: str.startswith("") is always True, so an empty-titled
    # page (a still-loading tab, about:blank, a titleless devtools/
    # background page) used to satisfy target_title.startswith(title) for
    # ANY target_title and get picked before the real match was ever
    # reached.
    browser = _FakeBrowser([_FakeContext([_FakePage(""), _FakePage("YouTube")])])

    page = asyncio.run(ChromeCdpElementInspector._find_page(browser, "YouTube"))

    assert page is not None
    assert asyncio.run(page.title()) == "YouTube"


def test_find_page_returns_none_when_only_empty_titled_pages_exist() -> None:
    browser = _FakeBrowser([_FakeContext([_FakePage(""), _FakePage("")])])

    page = asyncio.run(ChromeCdpElementInspector._find_page(browser, "YouTube"))

    assert page is None


def test_find_page_returns_none_when_nothing_matches() -> None:
    browser = _FakeBrowser([_FakeContext([_FakePage("Something else")])])

    page = asyncio.run(ChromeCdpElementInspector._find_page(browser, "YouTube"))

    assert page is None
