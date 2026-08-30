from __future__ import annotations

import pytest

from core.voice.intent import (
    Command,
    interpret,
    is_affirmative,
    is_fitness_exit_command,
    is_resign_command,
    is_stop_command,
)


def test_bare_music_request_has_empty_query() -> None:
    command = interpret("включи музыку", "ru")
    assert command is not None
    assert command.name == "open_media"
    assert command.params == {"kind": "music", "query": ""}


def test_bare_video_request_has_empty_query() -> None:
    command = interpret("открой видео", "ru")
    assert command is not None
    assert command.name == "open_media"
    assert command.params == {"kind": "video", "query": ""}


def test_specific_music_request_carries_the_query() -> None:
    command = interpret("поставь песню queen", "ru")
    assert command is not None
    assert command.params == {"kind": "music", "query": "queen"}


def test_specific_video_request_carries_the_query() -> None:
    command = interpret("открой видео с котиками", "ru")
    assert command is not None
    assert command.params == {"kind": "video", "query": "с котиками"}


def test_generic_open_app_still_works_for_non_media_targets() -> None:
    command = interpret("открой стим", "ru")
    assert command is not None
    assert command.name == "open_app"
    assert command.params == {"target": "стим"}


def test_media_request_with_filler_word_before_the_kind_noun_is_not_read_as_open_app() -> None:
    # Regression: "запусти мне песню"/"запусти любую песню" don't have the
    # kind noun immediately after the verb, so a strict-adjacency pattern
    # fell through to _OPEN_APP_PATTERNS and tried to open "мне песню" (or
    # "любую песню") as if it were an application name.
    command = interpret("запусти мне песню", "ru")
    assert command == Command(name="open_media", params={"kind": "music", "query": ""})

    command = interpret("запусти любую песню", "ru")
    assert command == Command(name="open_media", params={"kind": "music", "query": ""})

    command = interpret("включи мне музыку", "ru")
    assert command == Command(name="open_media", params={"kind": "music", "query": ""})


def test_close_app_trigger_ru() -> None:
    assert interpret("закрой телеграм", "ru") == Command(name="close_app", params={"target": "телеграм"})
    assert interpret("выйди из стима", "ru") == Command(name="close_app", params={"target": "стима"})


def test_close_app_trigger_en() -> None:
    assert interpret("close telegram", "en") == Command(name="close_app", params={"target": "telegram"})
    assert interpret("quit blender", "en") == Command(name="close_app", params={"target": "blender"})


def test_formal_shutdown_phrasing_is_not_misread_as_close_app() -> None:
    # Regression: "заверши" was briefly a close_app trigger verb too, which
    # meant a formal "заверши работу компьютера" (finish the computer's
    # work - a real way to phrase "shut down") got parsed as closing an app
    # literally named "работу компьютера" instead of shutting down.
    command = interpret("заверши работу компьютера", "ru")
    assert command is None or command.name != "close_app"


def test_english_media_pattern() -> None:
    command = interpret("play music", "en")
    assert command is not None
    assert command.name == "open_media"
    assert command.params["kind"] == "music"


def test_schedule_trigger_captures_raw_text() -> None:
    command = interpret("напомни мне позвонить маме в пятницу", "ru")
    assert command is not None
    assert command.name == "schedule_event"
    assert command.params == {"raw_text": "позвонить маме в пятницу"}


def test_schedule_trigger_with_no_details_has_empty_raw_text() -> None:
    command = interpret("добавь в планировщик", "ru")
    assert command is not None
    assert command.name == "schedule_event"
    assert command.params == {"raw_text": ""}


def test_schedule_trigger_does_not_shadow_open_media() -> None:
    command = interpret("поставь напоминание сходить к врачу", "ru")
    assert command is not None
    assert command.name == "schedule_event"

    media_command = interpret("поставь музыку", "ru")
    assert media_command is not None
    assert media_command.name == "open_media"


# --- messaging triggers (modules/messaging) ---------------------------------


def test_messaging_reply_trigger_bare_ru() -> None:
    assert interpret("ответь", "ru") == Command(name="messaging_reply", params={"raw_target": ""})


def test_messaging_reply_trigger_with_name_ru() -> None:
    assert interpret("ответь Ире", "ru") == Command(name="messaging_reply", params={"raw_target": "ире"})


def test_messaging_reply_trigger_en() -> None:
    assert interpret("reply", "en") == Command(name="messaging_reply", params={"raw_target": ""})
    assert interpret("reply Ira", "en") == Command(name="messaging_reply", params={"raw_target": "ira"})


def test_messaging_snooze_trigger_bare_ru() -> None:
    assert interpret("отложи", "ru") == Command(name="messaging_snooze", params={"raw_text": ""})


def test_messaging_snooze_trigger_with_duration_ru() -> None:
    assert interpret("отложи на 10 минут", "ru") == Command(
        name="messaging_snooze", params={"raw_text": "на 10 минут"}
    )


def test_messaging_watch_trigger_ru() -> None:
    # _normalize() strips punctuation (including '@') before any pattern
    # ever sees the text — same as every other trigger in this file — so
    # the captured raw_text never has a leading '@' regardless of how the
    # user said/wrote it. modules.messaging.service_layer._normalize_identifier
    # strips a leading '@' too, so this loses nothing in practice.
    assert interpret("следи за ira в телеграме", "ru") == Command(
        name="messaging_watch_contact", params={"raw_text": "ira в телеграме"}
    )
    assert interpret("отслеживай ira", "ru") == Command(
        name="messaging_watch_contact", params={"raw_text": "ira"}
    )


# --- ui_action trigger (modules/ui_automation) ------------------------------


def test_ui_action_trigger_click_ru() -> None:
    assert interpret("нажми на тренды", "ru") == Command(name="ui_action", params={"raw_text": "тренды"})
    assert interpret("кликни сохранить", "ru") == Command(name="ui_action", params={"raw_text": "сохранить"})


def test_ui_action_trigger_type_ru() -> None:
    assert interpret("напечатай привет мир", "ru") == Command(
        name="ui_action", params={"raw_text": "привет мир"}
    )
    assert interpret("введи текст письма", "ru") == Command(
        name="ui_action", params={"raw_text": "текст письма"}
    )


def test_ui_action_trigger_en() -> None:
    assert interpret("click on trends", "en") == Command(name="ui_action", params={"raw_text": "trends"})
    assert interpret("type hello world", "en") == Command(
        name="ui_action", params={"raw_text": "hello world"}
    )


def test_ui_action_does_not_shadow_open_app() -> None:
    # Deliberate design decision (see _UI_ACTION_PATTERNS' comment in
    # intent.py): "открой"/"open" is NOT a ui_action trigger verb, so a
    # compound instruction like this keeps matching _OPEN_APP_PATTERNS
    # instead of being swallowed here as a UI click/type request. Such
    # compound phrasing is expected to fall through interpret() entirely and
    # be resolved by the AI classifier via the registered "ui_action"
    # dispatcher command instead.
    command = interpret("открой консоль и напиши привет", "ru")
    assert command is not None
    assert command.name == "open_app"


def test_capabilities_trigger_ru() -> None:
    command = interpret("что ты умеешь", "ru")
    assert command == Command(name="list_capabilities", params={"language": "ru"})


def test_capabilities_trigger_en() -> None:
    command = interpret("what can you do", "en")
    assert command == Command(name="list_capabilities", params={"language": "en"})


# --- is_affirmative (fuzzy confirmation, e.g. for shutdown/restart) --------


def test_is_affirmative_exact_word() -> None:
    assert is_affirmative("да", "ru")


def test_is_affirmative_tolerates_extra_words() -> None:
    # Regression: a confirmation like "да, давай, выключай" used to require
    # a byte-for-byte "да" and nothing else, so real answers like this one
    # were read as a decline instead of a confirmation.
    assert is_affirmative("да, давай, выключай", "ru")
    assert is_affirmative("ну да выключай", "ru")


def test_is_affirmative_rejects_negative_answer() -> None:
    assert not is_affirmative("нет, не надо", "ru")
    assert not is_affirmative("отмена", "ru")


def test_is_affirmative_empty_answer_is_false() -> None:
    assert not is_affirmative("", "ru")


# --- is_stop_command (barge-in mid-speech interruption) --------------------


def test_is_stop_command_exact_word() -> None:
    assert is_stop_command("стоп", "ru")


def test_is_stop_command_tolerates_a_stray_extra_word_in_the_barge_in_window() -> None:
    # Regression: this used to require the *entire* transcribed window to
    # equal one of STOP_PHRASES exactly, so a rolling 1.2s barge-in window
    # that also happened to catch one extra stray word (background noise,
    # the assistant's own speech bleeding into the mic) meant the stop word
    # was never recognized even though it was clearly said.
    assert is_stop_command("экран стоп", "ru")
    assert is_stop_command("а ну хватит", "ru")


def test_is_stop_command_false_for_unrelated_speech() -> None:
    assert not is_stop_command("какая погода сегодня", "ru")


def test_is_stop_command_empty_text_is_false() -> None:
    assert not is_stop_command("", "ru")


# --- start_board_game (modules/board_games) ---------------------------------


def test_interpret_start_board_game_generic_phrase_has_no_kind() -> None:
    command = interpret("давай сыграем партию", "ru")
    assert command == Command(name="start_board_game", params={"game": ""})


def test_interpret_start_board_game_chess_phrase_carries_kind() -> None:
    command = interpret("давай сыграем в шахматы", "ru")
    assert command == Command(name="start_board_game", params={"game": "chess"})


def test_interpret_start_board_game_checkers_phrase_carries_kind() -> None:
    command = interpret("хочу сыграть в шашки", "ru")
    assert command == Command(name="start_board_game", params={"game": "checkers"})


# --- start_os_agent (modules/os_agent) ---------------------------------


def test_interpret_start_os_agent_ru() -> None:
    assert interpret("включи режим агента", "ru") == Command(name="start_os_agent", params={})
    assert interpret("активируй режим агента", "ru") == Command(name="start_os_agent", params={})


def test_interpret_start_os_agent_en() -> None:
    assert interpret("turn on agent mode", "en") == Command(name="start_os_agent", params={})


def test_interpret_open_app_launch_verb_drift_is_not_swallowed_by_os_agent() -> None:
    # Regression guard for the fuzzy-match collision found while adding
    # _OS_AGENT_START_PHRASES: a short "запусти X"-shaped phrase must not be
    # part of that set (see its own comment) precisely because it would
    # otherwise fuzzy-collide with unrelated open_app launch-verb phrasing.
    assert interpret("запустим стим", "ru") == Command(name="open_app", params={"target": "стим"})


# --- fitness_activate_context (modules/fitness_tracker) --------------------


def test_interpret_fitness_activate_context_ru() -> None:
    assert interpret("перейди в фитнес трекер", "ru") == Command(name="fitness_activate_context", params={})
    assert interpret("открой модуль спорта", "ru") == Command(name="fitness_activate_context", params={})


def test_interpret_fitness_activate_context_en() -> None:
    assert interpret("open the fitness tracker", "en") == Command(name="fitness_activate_context", params={})


def test_interpret_start_board_game_is_not_swallowed_by_fitness_activation() -> None:
    # Regression guard for the fuzzy-match collision found while choosing
    # _FITNESS_START_PHRASES: short "давай..."/"хочу..." openers (as the
    # task spec's own example "давай про показатели" was worded) collide
    # with _BOARD_GAME_PHRASES's "давай поиграем"/"хочу поиграть" — dropped
    # from the final phrase set for exactly this reason.
    assert interpret("давай сыграем", "ru") == Command(name="start_board_game", params={"game": ""})


def test_interpret_start_os_agent_is_not_swallowed_by_fitness_activation() -> None:
    # Same collision class: "активируй режим X" was considered for fitness
    # too and dropped because it fuzzy-collides with
    # _OS_AGENT_START_PHRASES's "активируй режим агента".
    assert interpret("активируй режим агента", "ru") == Command(name="start_os_agent", params={})


def test_is_fitness_exit_command_true_for_exit_phrase() -> None:
    assert is_fitness_exit_command("выйди из фитнес трекера", "ru")


def test_is_fitness_exit_command_true_for_bare_stop_word() -> None:
    # "хватит про спорт" literally contains the word "хватит", so a bare
    # "хватит" also matches via the same fuzzy window — consistent with
    # every other in-progress mode here treating a bare stop word as an
    # implicit exit.
    assert is_fitness_exit_command("хватит", "ru")


def test_is_fitness_exit_command_false_for_unrelated_speech() -> None:
    assert not is_fitness_exit_command("какая погода сегодня", "ru")


def test_is_fitness_exit_command_empty_text_is_false() -> None:
    assert not is_fitness_exit_command("", "ru")


# --- is_resign_command (mid-game "сдаюсь", distinct from is_stop_command) --


def test_is_resign_command_exact_word() -> None:
    assert is_resign_command("сдаюсь", "ru")


def test_is_resign_command_false_for_plain_stop_word() -> None:
    # "стоп" alone must NOT resign the game — see RESIGN_PHRASES's own
    # comment on why resign and stop are kept as separate concepts.
    assert not is_resign_command("стоп", "ru")


def test_is_resign_command_false_for_unrelated_speech() -> None:
    assert not is_resign_command("какая погода сегодня", "ru")


def test_is_resign_command_empty_text_is_false() -> None:
    assert not is_resign_command("", "ru")


# --- open_app/open_media/close_app verbs tolerate STT conjugation drift ----
# Regression: Whisper routinely transcribes a spoken imperative ("открой",
# "включи") as a different, similar-sounding conjugation of the same verb
# ("открою", "включим") even on otherwise-clean audio - measured directly via
# a real TTS->STT round trip, not a hypothetical. Since these patterns are
# anchored at the start of the utterance, that alone used to make the whole
# command fail to match and fall through to "не поняла команду".


def test_open_app_tolerates_future_tense_verb_drift() -> None:
    assert interpret("открою стим", "ru") == Command(name="open_app", params={"target": "стим"})
    assert interpret("откроем стим", "ru") == Command(name="open_app", params={"target": "стим"})


def test_open_app_tolerates_launch_verb_drift() -> None:
    assert interpret("запущу стим", "ru") == Command(name="open_app", params={"target": "стим"})
    assert interpret("запустим стим", "ru") == Command(name="open_app", params={"target": "стим"})


def test_media_verb_tolerates_conjugation_drift() -> None:
    assert interpret("включим музыку", "ru") == Command(name="open_media", params={"kind": "music", "query": ""})
    assert interpret("откроем видео", "ru") == Command(name="open_media", params={"kind": "video", "query": ""})
    assert interpret("поставим песню queen", "ru") == Command(
        name="open_media", params={"kind": "music", "query": "queen"}
    )


def test_close_app_tolerates_future_tense_verb_drift() -> None:
    assert interpret("закрою телеграм", "ru") == Command(name="close_app", params={"target": "телеграм"})
    assert interpret("закроем телеграм", "ru") == Command(name="close_app", params={"target": "телеграм"})


# --- shutdown/restart triggers tolerate minor phrasing noise ---------------


def test_shutdown_trigger_tolerates_stt_noise() -> None:
    command = interpret("выключи компьютир", "ru")
    assert command == Command(name="shutdown", params={})


def test_restart_trigger_tolerates_stt_noise() -> None:
    command = interpret("перезагрузи компьютир", "ru")
    assert command == Command(name="restart", params={})


# --- lock_screen trigger (distinct from shutdown) -------------------------


def test_lock_screen_trigger_ru() -> None:
    assert interpret("заблокируй экран", "ru") == Command(name="lock_screen", params={})


def test_lock_screen_trigger_uk() -> None:
    assert interpret("заблокуй комп'ютер", "uk") == Command(name="lock_screen", params={})


def test_lock_screen_trigger_en() -> None:
    assert interpret("lock my screen", "en") == Command(name="lock_screen", params={})


def test_lock_computer_is_not_misread_as_shutdown_ru() -> None:
    assert interpret("заблокируй компьютер", "ru") == Command(name="lock_screen", params={})


def test_lock_computer_is_not_misread_as_shutdown_en() -> None:
    assert interpret("lock the computer", "en") == Command(name="lock_screen", params={})


def test_shutdown_still_wins_for_its_own_phrasing() -> None:
    assert interpret("выключи компьютер", "ru") == Command(name="shutdown", params={})


# --- software installer (modules/software_installer) ---------------------


def test_install_known_program_by_name() -> None:
    assert interpret("установи vlc", "ru") == Command(name="software_install", params={"app": "vlc"})


def test_install_with_marker_word_claims_any_name() -> None:
    assert interpret("установи программу медиаплеер", "ru") == Command(
        name="software_install", params={"app": "медиаплеер"}
    )


def test_install_without_marker_and_unknown_name_falls_through() -> None:
    assert interpret("установи будильник на 7", "ru") is None


def test_install_does_not_steal_set_music() -> None:
    assert interpret("поставь музыку", "ru").name != "software_install"


def test_installer_button_next_ru() -> None:
    assert interpret("нажми далее", "ru") == Command(
        name="installer_click_button", params={"button": "next"}
    )


def test_installer_button_install_with_knopku() -> None:
    assert interpret("нажми кнопку установить", "ru") == Command(
        name="installer_click_button", params={"button": "install"}
    )


def test_installer_button_finish_en() -> None:
    assert interpret("click finish", "en") == Command(
        name="installer_click_button", params={"button": "finish"}
    )


def test_installer_button_ignores_unrecognized_label() -> None:
    assert interpret("нажми сохранить", "ru") != Command(
        name="installer_click_button", params={"button": "next"}
    )


# --- discussion mode (modules/discussion_mode) --------------------------


@pytest.mark.parametrize(
    "text", ["давай подискутируем", "режим дискуссии", "включи режим дискуссии"]
)
def test_discussion_mode_enter_phrase(text: str) -> None:
    assert interpret(text, "ru") == Command(name="start_discussion", params={})


# --- Weather (modules/weather) -----------------------------------------------


def test_weather_with_city_and_tomorrow_marker() -> None:
    command = interpret("какая погода завтра в Киеве", "ru")
    assert command == Command(name="weather_get", params={"city": "киеве", "when": "tomorrow"})


def test_weather_city_before_when_marker_also_works() -> None:
    command = interpret("погода в Киеве завтра", "ru")
    assert command == Command(name="weather_get", params={"city": "киеве", "when": "tomorrow"})


def test_weather_defaults_to_today_without_a_when_marker() -> None:
    command = interpret("какая погода в Одессе", "ru")
    assert command == Command(name="weather_get", params={"city": "одессе", "when": "today"})


def test_weather_day_after_tomorrow_is_not_swallowed_by_tomorrow() -> None:
    # Regression: "послезавтра" contains "завтра" as a substring - the
    # longer marker must win, or this would always be misread as "tomorrow".
    command = interpret("погода послезавтра в Киеве", "ru")
    assert command == Command(name="weather_get", params={"city": "киеве", "when": "day_after_tomorrow"})


def test_weather_without_a_city_leaves_city_empty_for_the_handler_to_reject() -> None:
    command = interpret("какая сегодня погода", "ru")
    assert command == Command(name="weather_get", params={"city": "", "when": "today"})


def test_weather_when_marker_preceded_by_a_preposition_does_not_swallow_the_city() -> None:
    # Regression, found live: "на завтра" (idiomatic "for tomorrow") ahead
    # of "в Киеве" used to be captured whole as the city ("завтра в киеве")
    # since the city pattern's capture group tolerates spaces and the
    # search started at "на завтра" (the first в/на it found) instead of
    # the real "в Киеве".
    command = interpret("Ок скажи мне погоду на завтра в киеве", "ru")
    assert command == Command(name="weather_get", params={"city": "киеве", "when": "tomorrow"})


def test_weather_english() -> None:
    command = interpret("what's the weather in London tomorrow", "en")
    assert command == Command(name="weather_get", params={"city": "london", "when": "tomorrow"})


def test_weather_city_with_vo_elision() -> None:
    # Regression, found live: "во Львове" (the standard Russian elision
    # spelling of "в" before a word starting with certain consonant
    # clusters) left city empty, since the pattern only recognized bare "в".
    command = interpret("погода во Львове", "ru")
    assert command == Command(name="weather_get", params={"city": "львове", "when": "today"})


# --- Weather: yesterday/day-before-yesterday/arbitrary day range ------------
# Found live: the app supports a full 7-day-back/7-day-forward range (see
# modules/weather/domain.py's resolve_day_offset) but interpret() only ever
# produced "today"/"tomorrow"/"day_after_tomorrow" - "какая погода вчера"
# had no rule-based path at all and fell through to the (unreliable) AI
# classifier chain for something that should be instant and deterministic,
# same reasoning as every other weather marker above.


def test_weather_yesterday_and_day_before_yesterday() -> None:
    assert interpret("какая погода вчера в Киеве", "ru") == Command(
        name="weather_get", params={"city": "киеве", "when": "yesterday"}
    )
    assert interpret("погода позавчера", "ru") == Command(
        name="weather_get", params={"city": "", "when": "day_before_yesterday"}
    )


def test_weather_day_before_yesterday_is_not_swallowed_by_yesterday() -> None:
    # Same substring-ordering regression as day_after_tomorrow/tomorrow —
    # "позавчера" contains "вчера".
    command = interpret("погода позавчера в Киеве", "ru")
    assert command == Command(name="weather_get", params={"city": "киеве", "when": "day_before_yesterday"})


def test_weather_arbitrary_day_range_forward_and_backward() -> None:
    assert interpret("погода в Киеве через 5 дней", "ru") == Command(
        name="weather_get", params={"city": "киеве", "when": "5"}
    )
    assert interpret("погода 3 дня назад в Одессе", "ru") == Command(
        name="weather_get", params={"city": "одессе", "when": "-3"}
    )


def test_weather_yesterday_and_arbitrary_range_ukrainian() -> None:
    assert interpret("яка погода вчора", "uk") == Command(
        name="weather_get", params={"city": "", "when": "yesterday"}
    )
    assert interpret("погода через 4 дні у Львові", "uk") == Command(
        name="weather_get", params={"city": "львові", "when": "4"}
    )


def test_weather_yesterday_and_arbitrary_range_english() -> None:
    assert interpret("what is the weather yesterday in Kyiv", "en") == Command(
        name="weather_get", params={"city": "kyiv", "when": "yesterday"}
    )
    assert interpret("what is the weather 3 days ago", "en") == Command(
        name="weather_get", params={"city": "", "when": "-3"}
    )


# --- System volume (core/dispatcher.py's set_volume/change_volume) ---------
# Regression: none of these had a rule-based pattern at all before - every
# phrase, even a clean common one, fell through interpret() entirely and
# depended on AI classification succeeding.


def test_system_volume_set_with_na() -> None:
    assert interpret("поставь громкость на 50", "ru") == Command(name="set_volume", params={"percent": "50"})


def test_system_volume_set_bare_number() -> None:
    assert interpret("громкость 50", "ru") == Command(name="set_volume", params={"percent": "50"})


def test_system_volume_set_with_percent_word() -> None:
    assert interpret("установи громкость 30 процентов", "ru") == Command(
        name="set_volume", params={"percent": "30"}
    )


def test_system_volume_set_with_do_regardless_of_verb() -> None:
    # "increase ... TO 100" means set it to 100, not raise it BY 100 - "до"
    # always means absolute regardless of which verb comes before it.
    assert interpret("увеличь мне громкость до 100 процентов", "ru") == Command(
        name="set_volume", params={"percent": "100"}
    )
    assert interpret("уменьши громкость до 0", "ru") == Command(name="set_volume", params={"percent": "0"})


def test_system_volume_increase_by_na_is_relative() -> None:
    assert interpret("увеличь громкость на 20", "ru") == Command(
        name="change_volume", params={"delta_percent": "20"}
    )
    assert interpret("увеличь мне громкость на 20", "ru") == Command(
        name="change_volume", params={"delta_percent": "20"}
    )


def test_system_volume_decrease_by_na_is_relative_and_negative() -> None:
    assert interpret("уменьши громкость на 30", "ru") == Command(
        name="change_volume", params={"delta_percent": "-30"}
    )
    assert interpret("убавь громкость на 15", "ru") == Command(
        name="change_volume", params={"delta_percent": "-15"}
    )


def test_system_volume_does_not_shadow_video_or_music_volume() -> None:
    assert interpret("громкость видео на 50", "ru") == Command(
        name="youtube_set_volume", params={"percent": "50"}
    )
    assert interpret("громкость музыки на 50", "ru") == Command(
        name="spotify_set_volume", params={"percent": "50"}
    )


def test_system_volume_english() -> None:
    assert interpret("set volume to 50", "en") == Command(name="set_volume", params={"percent": "50"})
    assert interpret("increase the volume by 20 percent", "en") == Command(
        name="change_volume", params={"delta_percent": "20"}
    )
    assert interpret("increase the volume to 100 percent", "en") == Command(
        name="set_volume", params={"percent": "100"}
    )


# Found live: "поднять громкость на ноутбуке до 10%" fell through the
# system-volume patterns entirely because they had zero tolerance for a
# device-name filler between "громкость" and the number.
def test_system_volume_tolerates_device_filler() -> None:
    assert interpret("подними громкость на ноутбуке на 20", "ru") == Command(
        name="change_volume", params={"delta_percent": "20"}
    )
    assert interpret("увеличь громкость на компьютере до 50", "ru") == Command(
        name="set_volume", params={"percent": "50"}
    )
    assert interpret("уменьши громкость на ноутбуке на 15", "ru") == Command(
        name="change_volume", params={"delta_percent": "-15"}
    )


# The assistant's own TTS output volume (core/dispatcher.py's
# set_assistant_volume/change_assistant_volume) — distinct from the OS
# volume above. Found missing entirely live: no rule-based path existed for
# "свою"/"личную" volume, so it fell to the AI free-text fallback with no
# real command behind it.
def test_assistant_volume_set_and_change() -> None:
    assert interpret("поставь личную громкость на 30", "ru") == Command(
        name="set_assistant_volume", params={"percent": "30"}
    )
    assert interpret("подними твою громкость на 10", "ru") == Command(
        name="change_assistant_volume", params={"delta_percent": "10"}
    )
    assert interpret("убавь свою громкость на 20", "ru") == Command(
        name="change_assistant_volume", params={"delta_percent": "-20"}
    )
    assert interpret("увеличь свою громкость до 100", "ru") == Command(
        name="set_assistant_volume", params={"percent": "100"}
    )


def test_assistant_volume_does_not_collide_with_system_volume() -> None:
    assert interpret("подними громкость на 20", "ru") == Command(
        name="change_volume", params={"delta_percent": "20"}
    )
    assert interpret("поставь громкость на 30", "ru") == Command(name="set_volume", params={"percent": "30"})


# --- Screen brightness (core/dispatcher.py's set_brightness/change_brightness)
# Mirrors the system-volume patterns one-for-one, keyed on "яркость" instead
# of "громкость". Same "до N = absolute, на N = relative" split.


def test_system_brightness_set_with_na_and_bare_number() -> None:
    assert interpret("поставь яркость на 50", "ru") == Command(
        name="set_brightness", params={"percent": "50"}
    )
    assert interpret("яркость 40", "ru") == Command(name="set_brightness", params={"percent": "40"})


def test_system_brightness_set_to_is_absolute_regardless_of_verb() -> None:
    assert interpret("увеличь яркость до 80 процентов", "ru") == Command(
        name="set_brightness", params={"percent": "80"}
    )
    assert interpret("уменьши яркость до 20", "ru") == Command(
        name="set_brightness", params={"percent": "20"}
    )


def test_system_brightness_increase_and_decrease_by_na_are_relative() -> None:
    assert interpret("прибавь яркость на 15", "ru") == Command(
        name="change_brightness", params={"delta_percent": "15"}
    )
    assert interpret("убавь яркость на 30", "ru") == Command(
        name="change_brightness", params={"delta_percent": "-30"}
    )


def test_system_brightness_tolerates_device_filler() -> None:
    assert interpret("подними яркость на ноутбуке на 20", "ru") == Command(
        name="change_brightness", params={"delta_percent": "20"}
    )
    assert interpret("установи яркость на компьютере до 50", "ru") == Command(
        name="set_brightness", params={"percent": "50"}
    )


def test_system_brightness_ukrainian_and_english() -> None:
    assert interpret("постав яскравість на 60", "uk") == Command(
        name="set_brightness", params={"percent": "60"}
    )
    assert interpret("set the screen brightness to 50", "en") == Command(
        name="set_brightness", params={"percent": "50"}
    )
    assert interpret("increase brightness by 10 percent", "en") == Command(
        name="change_brightness", params={"delta_percent": "10"}
    )
    assert interpret("dim the screen brightness by 25", "en") == Command(
        name="change_brightness", params={"delta_percent": "-25"}
    )


def test_system_brightness_does_not_collide_with_system_volume() -> None:
    assert interpret("поставь громкость на 30", "ru") == Command(name="set_volume", params={"percent": "30"})
    assert interpret("прибавь громкость на 15", "ru") == Command(
        name="change_volume", params={"delta_percent": "15"}
    )


def test_bare_brighter_without_a_number_is_not_matched_by_rules() -> None:
    # Deliberately left to the embedding classifier's change_brightness with
    # a default step, exactly as "сделай погромче" is for volume.
    assert interpret("сделай экран ярче", "ru") is None


# --- YouTube (modules/youtube_control) --------------------------------------


def test_youtube_search_and_play_carries_the_query() -> None:
    command = interpret("включи на ютубе лоу фай бит", "ru")
    assert command == Command(name="youtube_search_and_play", params={"query": "лоу фай бит"})


def test_youtube_search_is_not_swallowed_by_open_media() -> None:
    # Regression: "видео" inside the query is itself an open_media kind
    # word, and "включи" is shared with both open_media and open_app.
    command = interpret("включи на ютубе видео с котиками", "ru")
    assert command == Command(name="youtube_search_and_play", params={"query": "видео с котиками"})


def test_bare_video_open_media_still_works_after_adding_youtube_patterns() -> None:
    assert interpret("открой видео", "ru") == Command(name="open_media", params={"kind": "video", "query": ""})


def test_bare_pause_is_generic_media_pause() -> None:
    assert interpret("пауза", "ru") == Command(name="media_pause", params={})


def test_bare_resume_is_generic_media_resume() -> None:
    assert interpret("продолжи", "ru") == Command(name="media_resume", params={})


def test_bare_next_is_generic_media_next() -> None:
    assert interpret("следующее", "ru") == Command(name="media_next", params={})


def test_explicit_video_pause_targets_youtube() -> None:
    assert interpret("пауза видео", "ru") == Command(name="youtube_pause", params={})


def test_explicit_video_resume_targets_youtube() -> None:
    assert interpret("продолжи видео", "ru") == Command(name="youtube_resume", params={})


def test_explicit_video_next_targets_youtube() -> None:
    assert interpret("следующее видео", "ru") == Command(name="youtube_next", params={})


def test_explicit_music_pause_targets_spotify() -> None:
    assert interpret("пауза музыки", "ru") == Command(name="spotify_pause", params={})


def test_explicit_music_resume_targets_spotify() -> None:
    assert interpret("продолжи музыку", "ru") == Command(name="spotify_resume", params={})


def test_explicit_music_next_targets_spotify() -> None:
    assert interpret("следующий трек", "ru") == Command(name="spotify_next", params={})


def test_spotify_search_and_play_carries_the_query() -> None:
    command = interpret("включи на спотифае лоу фай бит", "ru")
    assert command == Command(name="spotify_search_and_play", params={"query": "лоу фай бит"})


def test_spotify_set_volume_requires_the_word_music() -> None:
    command = interpret("громкость музыки на 70 процентов", "ru")
    assert command == Command(name="spotify_set_volume", params={"percent": "70"})


def test_bare_system_volume_phrase_is_not_claimed_by_spotify() -> None:
    assert interpret("сделай потише", "ru") is None


def test_youtube_seek_forward_defaults_to_ten_seconds() -> None:
    assert interpret("перемотай вперёд", "ru") == Command(name="youtube_seek", params={"offset_seconds": "10"})


def test_youtube_seek_forward_with_an_explicit_duration() -> None:
    command = interpret("перемотай вперёд на 30 секунд", "ru")
    assert command == Command(name="youtube_seek", params={"offset_seconds": "30"})


def test_youtube_seek_backward_is_negative() -> None:
    command = interpret("перемотай назад на 15 секунд", "ru")
    assert command == Command(name="youtube_seek", params={"offset_seconds": "-15"})


def test_youtube_set_volume_requires_the_word_video() -> None:
    command = interpret("громкость видео на 70 процентов", "ru")
    assert command == Command(name="youtube_set_volume", params={"percent": "70"})


def test_bare_system_volume_phrase_is_not_claimed_by_youtube() -> None:
    # "громче"/"сделай потише" etc. must keep falling through to
    # modules/hardware_adaptive/command_classifier.py (checked later in
    # core/voice/pipeline.py) — interpret() must return None for these so
    # they aren't permanently shadowed by the YouTube volume pattern.
    assert interpret("сделай потише", "ru") is None
    assert interpret("громче", "ru") is None


def test_youtube_set_speed_is_voiced_as_a_percentage() -> None:
    # "1.5" doesn't survive _normalize() (it strips "."), so speed is voiced
    # as a whole-number percentage instead, same convention as volume.
    command = interpret("скорость видео на 150 процентов", "ru")
    assert command == Command(name="youtube_set_speed", params={"rate": "1.5"})


def test_youtube_set_speed_at_full_speed() -> None:
    command = interpret("скорость видео на 100", "ru")
    assert command == Command(name="youtube_set_speed", params={"rate": "1.0"})


# --- image generation (modules/image_generation) ----------------------------


def test_generate_image_carries_the_prompt() -> None:
    command = interpret("сгенерируй изображение кот в очках", "ru")
    assert command == Command(name="generate_image", params={"prompt": "кот в очках"})


def test_draw_alias_also_triggers_image_generation() -> None:
    command = interpret("нарисуй космический корабль", "ru")
    assert command == Command(name="generate_image", params={"prompt": "космический корабль"})


def test_generate_image_english() -> None:
    command = interpret("generate an image of a cat", "en")
    assert command == Command(name="generate_image", params={"prompt": "a cat"})


# --- text editing (modules/text_editing) ------------------------------------


def test_edit_pending_message_bare() -> None:
    assert interpret("отредактируй сообщение", "ru") == Command(
        name="edit_pending_message", params={"raw_target": ""}
    )


def test_edit_pending_message_with_target() -> None:
    assert interpret("отредактируй сообщение от Иры", "ru") == Command(
        name="edit_pending_message", params={"raw_target": "иры"}
    )


def test_edit_pending_message_english() -> None:
    assert interpret("edit message from Ira", "en") == Command(
        name="edit_pending_message", params={"raw_target": "ira"}
    )


# --- code analysis (modules/code_analysis) -----------------------------------


def test_analyze_code_trigger() -> None:
    assert interpret("проанализируй код", "ru") == Command(name="analyze_active_editor", params={})


def test_explain_code_trigger() -> None:
    assert interpret("объясни код", "ru") == Command(name="analyze_active_editor", params={})


def test_analyze_code_trigger_english() -> None:
    assert interpret("explain the code", "en") == Command(name="analyze_active_editor", params={})


def test_analyze_code_trigger_does_not_match_with_extra_words() -> None:
    # Deliberately exact-match, no captured group — anything beyond the bare
    # trigger phrase (the actual instruction) is asked as a follow-up
    # question instead, see core/voice/pipeline.py's
    # _resolve_analyze_active_editor.
    assert interpret("проанализируй код на баги", "ru") is None
