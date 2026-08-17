# Icon templates for screen_fallback.py

`screen_fallback.find_icon_on_screen(template_name)` matches these against
a screenshot of the active Figma window (OpenCV `TM_CCOEFF_NORMED`), so it
can click a button without a hardcoded coordinate that would break across
screen resolutions / OS scaling / Figma UI changes.

Not bundled — this repo can't ship real Figma UI screenshots. To add one:

1. Take a screenshot of Figma at the resolution/OS scale you actually use.
2. Crop tightly around just the icon (no surrounding whitespace/label —
   tighter crops match more reliably).
3. Save as a PNG here, named exactly as referenced in `screen_fallback.py`:
   - `align_left.png`, `align_right.png`, `align_top.png`, `align_bottom.png`
   - `align_center_horizontal.png`, `align_center_vertical.png`

Until a given file exists, `find_icon_on_screen` returns `None` for it and
the corresponding fallback action reports "couldn't do that" rather than
guessing — see `screen_fallback.align`.
