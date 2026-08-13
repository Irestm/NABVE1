from __future__ import annotations

from core.voice.intent import Command, interpret, is_affirmative, is_resign_command, is_stop_command


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
