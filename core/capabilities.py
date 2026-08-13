from __future__ import annotations

# Spoken/returned verbatim by "list_capabilities" (see core/dispatcher.py and
# core/voice/intent.py's _CAPABILITIES_PHRASES) when the user asks something
# like "что ты умеешь?" — a hand-curated, human-readable summary rather than
# a dump of CommandDescriptor.description strings (those are written for the
# AI intent classifier, not for a person listening to TTS). Keep this in
# sync with what's actually wired in core/bootstrap.py when a feature is
# added or removed.
CAPABILITIES_MESSAGES: dict[str, str] = {
    "ru": (
        "Вот что я умею. Открывать приложения и игры голосом — скажите «открой» и название, "
        "я сама разберусь, даже если распознавание речи исказит его. Закрывать их — скажите "
        "«закрой» и название. Включать музыку или видео на "
        "Ютубе: назовёте конкретное — открою сразу, не назовёте — спрошу, какое у вас настроение, "
        "и подберу сама. Записывать дела и напоминания в планировщик — скажите «напомни мне» или "
        "«запиши в планировщик», что и когда, дату и время пойму даже из «завтра» или «в пятницу». "
        "Вести календарь событий и напоминать о них голосом заранее. Хранить пароли. "
        "Искать в интернете. Управлять окнами, мышью и клавиатурой. "
        "Выключать и перезагружать компьютер. Отвечать на обычные вопросы как ИИ, когда готовой "
        "команды нет. А ещё у меня есть стоп-слово — скажите его, и я перестану реагировать на "
        "что-либо, пока вы не повторите его снова. Голос, стиль общения и стоп-слово настраиваются "
        "при первом знакомстве."
    ),
    "uk": (
        "Ось що я вмію. Відкривати застосунки та ігри голосом — скажіть «відкрий» і назву, я сама "
        "розберуся, навіть якщо розпізнавання мовлення її спотворить. Закривати їх — скажіть "
        "«закрий» і назву. Вмикати музику чи відео на "
        "Ютубі: назвете конкретне — відкрию одразу, не назвете — запитаю, який у вас настрій, і "
        "підберу сама. Записувати справи й нагадування в планувальник — скажіть «нагадай мені» або "
        "«запиши в планувальник», що і коли. Вести календар подій і нагадувати про них голосом "
        "заздалегідь. Зберігати паролі. Шукати в "
        "інтернеті. Керувати вікнами, мишею та клавіатурою. Вимикати й перезавантажувати комп'ютер. "
        "Відповідати на звичайні запитання як ШІ, коли готової команди немає. А ще в мене є "
        "стоп-слово — скажіть його, і я перестану реагувати на щось, доки ви не повторите його знову."
    ),
    "en": (
        "Here's what I can do. Open apps and games by voice — just say \"open\" and the name, I'll "
        "figure it out even if speech recognition garbles it. Close them — just say \"close\" and the "
        "name. Play music or video on YouTube: name "
        "something specific and I'll open it right away, or don't and I'll ask about your mood and "
        "pick something myself. Add tasks and reminders to the planner — say \"remind me\" or \"add "
        "to the planner\", what and when, I can work out dates like \"tomorrow\" or \"on Friday\". "
        "Keep a calendar of events and announce them out loud ahead of time. Store passwords. "
        "Search the web. Control windows, the mouse, and the keyboard. "
        "Shut down and restart the computer. Answer ordinary questions like a regular AI when there's "
        "no matching command. I also have a stop word — say it and I'll stop responding to anything "
        "until you say it again. Voice, communication style, and the stop word are all set up the "
        "first time we talk."
    ),
}
