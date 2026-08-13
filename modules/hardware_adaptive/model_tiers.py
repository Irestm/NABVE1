from __future__ import annotations

from dataclasses import dataclass

from modules.hardware_adaptive.hardware_detector import HardwareProfile

TIER_NONE = "none"
TIER_MID = "mid"
TIER_HIGH = "high"

# NVIDIA CUDA GPU is a hard requirement for the local model. Below this VRAM
# even the smallest supported tier isn't viable, so the local model is
# disabled entirely and every request goes through ai_bridge instead.
MIN_VRAM_GB_FOR_LOCAL = 4

_HIGH_TIER_MIN_VRAM_GB = 6
_HIGH_TIER_MIN_RAM_GB = 16
_MID_TIER_MIN_RAM_GB = 16


@dataclass(frozen=True)
class ModelTierSpec:
    tier: str
    model_name: str
    quantization: str
    min_ram_gb: int
    min_vram_gb: int
    example_gpu: str
    description: str


MODEL_TIERS: dict[str, ModelTierSpec] = {
    TIER_MID: ModelTierSpec(
        tier=TIER_MID,
        model_name="Qwen2.5-3B-Instruct",
        quantization="Q4_K_M GGUF",
        min_ram_gb=_MID_TIER_MIN_RAM_GB,
        min_vram_gb=MIN_VRAM_GB_FOR_LOCAL,
        example_gpu="RTX 2050 (4GB VRAM)",
        description=(
            "Minimum supported tier: 16GB DDR4 RAM, an i5-10400-class CPU, and a "
            "4GB+ CUDA GPU. Runs Qwen2.5-3B (or Phi-3-mini) as a Q4 GGUF model, "
            "fully on GPU."
        ),
    ),
    TIER_HIGH: ModelTierSpec(
        tier=TIER_HIGH,
        model_name="Qwen2.5-7B-Instruct",
        quantization="Q4_K_M/Q5_K_M GGUF",
        min_ram_gb=_HIGH_TIER_MIN_RAM_GB,
        min_vram_gb=_HIGH_TIER_MIN_VRAM_GB,
        example_gpu="RTX 4050 (6GB+ VRAM)",
        description=(
            "16GB+ DDR5 RAM, a current-generation CPU, and a 6GB+ CUDA GPU. Runs "
            "Qwen2.5-7B/Llama-3-8B as a Q4/Q5 GGUF model, fully on GPU."
        ),
    ),
}


def select_tier(hardware_profile: HardwareProfile | dict) -> str:
    """Picks a local model tier from a hardware profile dict shaped like
    hardware_detector.detect_hardware()'s return value. No NVIDIA GPU, or less
    than MIN_VRAM_GB_FOR_LOCAL VRAM, disables the local model entirely
    (TIER_NONE) — callers must fall back to ai_bridge in that case."""
    vram_gb = hardware_profile.get("vram_gb", 0)
    ram_gb = hardware_profile.get("ram_gb", 0)

    if vram_gb < MIN_VRAM_GB_FOR_LOCAL:
        return TIER_NONE

    if vram_gb >= _HIGH_TIER_MIN_VRAM_GB and ram_gb >= _HIGH_TIER_MIN_RAM_GB:
        return TIER_HIGH

    return TIER_MID
