from __future__ import annotations

from modules.wordpress_bridge.wp_draft_publisher import PROFILES_DIR, WordPressSession, _profile_dir_for


def test_profile_dir_is_stable_and_scoped_under_profiles_dir() -> None:
    first = _profile_dir_for("https://example.com")
    second = _profile_dir_for("https://example.com")
    assert first == second
    assert first.parent == PROFILES_DIR
    assert "example_com" in first.name


def test_profile_dir_differs_per_site() -> None:
    assert _profile_dir_for("https://example.com") != _profile_dir_for("https://other-site.com")


def test_session_strips_trailing_slash() -> None:
    session = WordPressSession("https://example.com/")
    assert session.site_url == "https://example.com"
