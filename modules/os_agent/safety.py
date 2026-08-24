from __future__ import annotations

import re

from modules.ui_automation.domain import UIStep

# press_key: only pure navigation/focus-movement keys are free — anything
# else (Return/Enter above all, which routinely submits a form or a search
# box) is gated by default.
_FREE_KEYS = {
    "tab", "shift+tab", "up", "down", "left", "right",
    "page_up", "page_down", "pageup", "pagedown", "home", "end", "escape", "esc",
}

# click: free only if the target's AT-SPI/CDP role looks like pure navigation
# (opening/selecting something to look at, not committing/destroying
# anything) — mirrors the role vocabulary modules/ui_automation/announce.py
# already speaks about.
_NAV_ROLES = {"menu item", "check menu item", "page tab", "list item", "link", "tree item"}

# Regardless of role, a name containing one of these (ru/uk/en) keywords
# forces the write tier — e.g. a "push button" named "Отправить" is
# obviously gated already (role not in _NAV_ROLES), but a "link"-role element
# named "Удалить аккаунт" must NOT be treated as free navigation just
# because its role looks like one.
_COMMIT_KEYWORDS = re.compile(
    r"сохран|удал|відправ|отправ|надісл|купи|оплат|підтверд|подтверд|заверш|перевод|списат|"
    r"\bsave\b|\bdelete\b|\bremove\b|\bsubmit\b|\bsend\b|\bbuy\b|\bpay\b|\bconfirm\b|\bcheckout\b",
    re.IGNORECASE,
)


def is_write_action(step: UIStep) -> bool:
    """True = gated (queued, never executed until the end-of-task spoken
    confirmation); False = free (executed immediately, see runner.py). Every
    branch fails safe toward True — an unrecognized key, an unrecognized
    role, or a name that can't be read at all all gate by default, per the
    plan's explicit "любая неопределённость — write" rule."""
    if step.action == "type_text":
        return True
    if step.action == "press_key":
        key = (step.key or "").strip().lower()
        return key not in _FREE_KEYS
    # click
    element = step.element
    if element is None:
        return True
    if element.role not in _NAV_ROLES:
        return True
    return bool(_COMMIT_KEYWORDS.search(element.name or ""))
