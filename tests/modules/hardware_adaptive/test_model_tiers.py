from __future__ import annotations

from modules.hardware_adaptive import model_tiers


def test_select_tier_none_when_vram_below_minimum() -> None:
    profile = {"ram_gb": 32, "vram_gb": 2, "cpu_tier": "high", "cpu_model": "x", "gpu_name": "y"}

    assert model_tiers.select_tier(profile) == model_tiers.TIER_NONE


def test_select_tier_none_when_no_gpu_at_all() -> None:
    profile = {"ram_gb": 32, "vram_gb": 0, "cpu_tier": "high", "cpu_model": "x", "gpu_name": None}

    assert model_tiers.select_tier(profile) == model_tiers.TIER_NONE


def test_select_tier_mid_at_minimum_viable_hardware() -> None:
    profile = {"ram_gb": 16, "vram_gb": 4, "cpu_tier": "mid", "cpu_model": "x", "gpu_name": "y"}

    assert model_tiers.select_tier(profile) == model_tiers.TIER_MID


def test_select_tier_mid_when_vram_high_but_ram_insufficient() -> None:
    profile = {"ram_gb": 8, "vram_gb": 8, "cpu_tier": "high", "cpu_model": "x", "gpu_name": "y"}

    assert model_tiers.select_tier(profile) == model_tiers.TIER_MID


def test_select_tier_mid_when_ram_high_but_vram_insufficient_for_high_tier() -> None:
    profile = {"ram_gb": 32, "vram_gb": 4, "cpu_tier": "high", "cpu_model": "x", "gpu_name": "y"}

    assert model_tiers.select_tier(profile) == model_tiers.TIER_MID


def test_select_tier_high_when_both_thresholds_met() -> None:
    profile = {"ram_gb": 16, "vram_gb": 6, "cpu_tier": "high", "cpu_model": "x", "gpu_name": "y"}

    assert model_tiers.select_tier(profile) == model_tiers.TIER_HIGH


def test_select_tier_accepts_plain_dict_missing_keys() -> None:
    assert model_tiers.select_tier({}) == model_tiers.TIER_NONE


def test_model_tiers_dict_has_a_spec_for_mid_and_high() -> None:
    assert set(model_tiers.MODEL_TIERS) == {model_tiers.TIER_MID, model_tiers.TIER_HIGH}
    assert model_tiers.MODEL_TIERS[model_tiers.TIER_MID].min_vram_gb == model_tiers.MIN_VRAM_GB_FOR_LOCAL
