"""Tests for the Berg Agents UI theme module."""

from __future__ import annotations

import pytest

from berg_agents.ui.theme import sync
from berg_agents.ui.theme.tokens import colors


def test_palette_exposes_brand_stops() -> None:
    assert colors.BRAND_PURPLE == "#7d029c"
    assert colors.BRAND_BLUE == "#3b528b"
    assert colors.BRAND_TEAL == "#21908c"


def test_palette_dict_matches_module_constants() -> None:
    assert colors.PALETTE["brand_purple"] == colors.BRAND_PURPLE
    assert colors.PALETTE["brand_blue"] == colors.BRAND_BLUE
    assert colors.PALETTE["brand_teal"] == colors.BRAND_TEAL
    assert colors.PALETTE["text"] == colors.TEXT
    assert colors.PALETTE["bg"] == colors.BG


def test_gradient_brand_contains_three_stops() -> None:
    g = colors.GRADIENT_BRAND
    assert colors.BRAND_PURPLE in g
    assert colors.BRAND_BLUE in g
    assert colors.BRAND_TEAL in g
    assert "135deg" in g


def test_sync_round_trip(tmp_path, monkeypatch) -> None:
    """Writing then re-checking should report no drift."""
    fake_docs_styles = tmp_path / "docs" / "styles"
    fake_docs_styles.mkdir(parents=True)
    # The sync module hard-codes a path; rebind to point at our tmp dir.
    monkeypatch.setattr(sync, "_DOCS_STYLES", fake_docs_styles)

    assert sync.sync() is True
    assert sync.check() is True


def test_sync_check_detects_drift(tmp_path, monkeypatch) -> None:
    fake_docs_styles = tmp_path / "docs" / "styles"
    fake_docs_styles.mkdir(parents=True)
    monkeypatch.setattr(sync, "_DOCS_STYLES", fake_docs_styles)
    sync.sync()
    # Tamper with the generated file.
    (fake_docs_styles / "custom.css").write_text(
        "/* tampered */\n", encoding="utf-8"
    )
    assert sync.check() is False


def test_sync_skips_when_docs_styles_missing(tmp_path, monkeypatch) -> None:
    """If docs/styles/ doesn't exist (clean checkout), sync is a no-op success."""
    fake_docs_styles = tmp_path / "no_such_dir" / "styles"
    monkeypatch.setattr(sync, "_DOCS_STYLES", fake_docs_styles)
    assert sync.sync() is True
    assert sync.check() is True


@pytest.mark.parametrize(
    "attr,hex_value",
    [
        ("TEXT", "#010a13"),
        ("BG", "#fbf7fb"),
        ("STATUS_SUCCESS", "#21908c"),
        ("STATUS_ERROR", "#d73027"),
    ],
)
def test_palette_semantic_colors(attr, hex_value) -> None:
    assert getattr(colors, attr) == hex_value
