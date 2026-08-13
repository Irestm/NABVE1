from __future__ import annotations

from modules.task_orchestrator.domain import TaskPlan

# One shared source of the spoken plan announcement — same reasoning as
# modules.ui_automation.announce: this needs to stay short and generic
# rather than narrating every step in maintainer-facing command language,
# since command descriptions (see core/dispatcher.py's `description=`
# strings) are written for the AI classifier, not for a person listening to
# TTS (see core/capabilities.py's own comment on that distinction).
_TEMPLATE = {
    "ru": "Выполняю составную задачу из {count} шагов: {goal}.",
    "uk": "Виконую складену задачу з {count} кроків: {goal}.",
    "en": "Running a {count}-step task: {goal}.",
}


def describe_plan(plan: TaskPlan, language: str) -> str:
    template = _TEMPLATE.get(language, _TEMPLATE["ru"])
    return template.format(count=len(plan.steps), goal=plan.goal_text)
