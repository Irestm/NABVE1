from __future__ import annotations

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
