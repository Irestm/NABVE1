# Installer button templates

Reference crops for `screen_fallback_installer.py`'s OpenCV template
matching (scenario Б — driving a third-party GUI installer wizard by
voice: "нажми далее"). None are bundled — this repo can't ship
screenshots of other vendors' installer chrome.

Capture your own: run the installer, screenshot it, crop **just** the
button (the labelled rectangle, no surrounding padding), save as grayscale
PNG under this directory with one of the names below. More than one crop
per button is fine — they're tried in order until one matches at
confidence ≥ 0.86.

| Button  | Template file names                                             |
|---------|---------------------------------------------------------------|
| next    | `next_en.png`, `next_ru.png`, `continue_en.png`, `dalee_ru.png` |
| install | `install_en.png`, `install_ru.png`, `ustanovit_ru.png`          |
| finish  | `finish_en.png`, `finish_ru.png`, `gotovo_ru.png`, `done_en.png`|
| accept  | `accept_en.png`, `agree_en.png`, `prinyat_ru.png`, `soglasen_ru.png` |

A crop taken at the same OS display scaling as when you use it matches
most reliably; template matching here is not scale-invariant.
