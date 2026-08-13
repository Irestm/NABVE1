from __future__ import annotations

from typing import Any

from core.dispatcher import CommandDispatcher
from modules.messaging import service_layer
from modules.messaging.uow import MessagingUnitOfWork


def _looks_like_telegram_identifier(identifier: str) -> bool:
    """A real Telegram @username or phone number is always plain ASCII with
    no spaces — a spoken "следи за Ирой" that never got resolved to an
    actual @username produces an identifier that can NEVER match
    modules/telegram/watcher.py's `sender_identifier` (a real username, or
    the numeric user id for a contact with none), since that comparison is
    deliberately literal (see service_layer._normalize_identifier). Without
    this check, watching such a contact used to silently accept it and then
    just never fire, with nothing telling the user why. Deliberately loose
    (no length/charset check beyond this) so it doesn't reject anything a
    real username or phone number could actually look like."""
    return identifier.isascii() and " " not in identifier


async def _handle_watch_contact(params: dict[str, Any]) -> dict[str, Any]:
    identifier = params.get("identifier")
    if not identifier:
        raise ValueError("Missing required parameter 'identifier'")
    source = params.get("source") or "telegram"
    if source == "telegram" and not _looks_like_telegram_identifier(identifier):
        raise ValueError(
            f"«{identifier}» не похоже на телеграм-username или номер телефона. Назовите точный "
            "@username контакта — отслеживание по одному только имени пока не поддерживается."
        )
    note = params.get("note", "")
    contact_id = service_layer.add_watched_contact(MessagingUnitOfWork(), source, identifier, note)
    return {
        "id": contact_id,
        "identifier": identifier,
        "message": f"Слежу за сообщениями от {identifier}.",
    }


async def _handle_list_watched(_params: dict[str, Any]) -> dict[str, Any]:
    contacts = service_layer.list_watched_contacts(MessagingUnitOfWork())
    if contacts:
        listed = "; ".join(contact.identifier for contact in contacts)
        message = f"Отслеживаю: {listed}."
    else:
        message = "Список отслеживаемых контактов пуст."
    return {
        "contacts": [
            {"id": c.id, "source": c.source, "identifier": c.identifier, "note": c.note}
            for c in contacts
        ],
        "message": message,
    }


async def _handle_reply(params: dict[str, Any]) -> dict[str, Any]:
    """Dumb executor — by the time this runs, `message_id`/`text` are
    already resolved (which pending message, the punctuation-cleaned
    dictated text) and already confirmed by the user, via
    core/voice/pipeline.py._resolve_messaging_reply. Registered
    dangerous=True (see the module's design notes) specifically so a
    direct /api/command call — which never goes through that resolver —
    still can't send a real message with zero confirmation."""
    message_id = params.get("message_id")
    text = params.get("text")
    if message_id is None:
        raise ValueError("Missing required parameter 'message_id'")
    if not text:
        raise ValueError("Missing required parameter 'text'")

    pending = service_layer.get_message(MessagingUnitOfWork(), int(message_id))
    if pending is None:
        raise ValueError(f"No pending message with id {message_id}")
    if pending.source != "telegram":
        raise ValueError(f"Ответ пока не поддерживается для источника '{pending.source}'.")

    # NABVE1 has no Telegram client of its own — this just queues the reply
    # for a separate bot process to actually deliver (see
    # modules/messaging/BRIDGE.md). Queuing, not confirmed delivery, is what
    # "replied" means below, same trust-the-send assumption the old
    # synchronous telegram_service_layer.send_message() call made.
    service_layer.queue_outbound_message(MessagingUnitOfWork(), pending.source, pending.sender_identifier, text)

    # A new message from the same contact can merge into this row (see
    # service_layer.record_incoming_message) at any point between when the
    # voice resolver first identified `pending` and right now — the whole
    # "which message / what to say / confirm?" exchange, plus the
    # send_message round-trip above, is real elapsed time for that to
    # happen in. Marking REPLIED unconditionally would silently fold that
    # arrival's text into a row now marked "handled" without the user ever
    # having heard/addressed it. `expected_received_at`, when the caller
    # supplied it (core/voice/pipeline.py always does; a raw /api/command
    # call generally won't, since it has no such window to race against —
    # mark replied as before in that case), is what `pending.received_at`
    # was at that original resolve; only mark replied if nothing merged in
    # since.
    expected_received_at = params.get("expected_received_at")
    if expected_received_at is None:
        service_layer.mark_replied(MessagingUnitOfWork(), pending.id)
    else:
        current = service_layer.get_message(MessagingUnitOfWork(), pending.id)
        unchanged = (
            current is not None
            and current.received_at is not None
            and current.received_at.isoformat() == expected_received_at
        )
        if unchanged:
            service_layer.mark_replied(MessagingUnitOfWork(), pending.id)
    return {"message_id": pending.id, "message": "Отправлено."}


async def _handle_snooze(params: dict[str, Any]) -> dict[str, Any]:
    message_id = params.get("message_id")
    minutes = params.get("minutes")
    if message_id is None:
        raise ValueError("Missing required parameter 'message_id'")
    if minutes is None:
        raise ValueError("Missing required parameter 'minutes'")

    minutes = int(minutes)
    ok = service_layer.snooze(MessagingUnitOfWork(), int(message_id), minutes)
    if not ok:
        raise ValueError(f"No pending message with id {message_id}")
    return {
        "message_id": int(message_id),
        "minutes": minutes,
        "message": f"Отложено на {minutes} мин.",
    }


def register_commands(dispatcher: CommandDispatcher) -> None:
    # Description text below is written for two different readers at once,
    # matching modules/ui_automation/handlers.py's "ui_action" precedent:
    # (1) the AI classifier (modules/ai_bridge/intent_classifier.py), which
    # reads these to decide what to extract from unpatterned free speech —
    # for these three commands that's always the same raw_target/raw_text
    # shorthand core/voice/intent.py's own regex patterns also produce; (2)
    # a raw /api/command caller, for whom "identifier"/"message_id"/"text"/
    # "minutes" are what the *handler function itself* actually requires.
    # The handlers above only ever receive the fully-resolved second shape —
    # core/voice/pipeline.py's resolvers rewrite raw_target/raw_text into it
    # before dispatch() is ever called from the voice loop.
    dispatcher.register(
        "messaging_watch_contact",
        _handle_watch_contact,
        dangerous=False,
        description=(
            "Start watching a contact for incoming messages, given a spoken description of who "
            "(raw_text) — e.g. 'следи за @ira в телеграме'. Handler itself expects identifier "
            "(exact @username/phone), source (defaults to 'telegram'), optional note."
        ),
    )
    dispatcher.register(
        "messaging_list_watched",
        _handle_list_watched,
        dangerous=False,
        description="List currently watched contacts.",
    )
    dispatcher.register(
        "messaging_reply",
        _handle_reply,
        dangerous=True,
        description=(
            "Reply to a pending message from a watched contact, optionally naming who (raw_target) "
            "— e.g. 'ответь Ире'. Handler itself expects message_id and the already-dictated text; "
            "requires confirmation."
        ),
    )
    dispatcher.register(
        "messaging_snooze",
        _handle_snooze,
        dangerous=False,
        description=(
            "Snooze a pending message from a watched contact for later, from a spoken description "
            "(raw_text) — e.g. 'отложи Иру на 10 минут'. Handler itself expects message_id and minutes."
        ),
    )
