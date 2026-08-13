from __future__ import annotations

# User-editable fixed prompts. Add/remove/edit entries here; each must contain
# a "{input}" placeholder that gets filled with the user's free-text input
# (empty string if none was given).
PRESET_PROMPTS: dict[str, str] = {
    "summarize": "Summarize the following:\n\n{input}",
    "translate_en": "Translate the following to English:\n\n{input}",
    "explain": "Explain this simply:\n\n{input}",
}
