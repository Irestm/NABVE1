from __future__ import annotations

# No dispatcher commands of its own — connecting/disconnecting an account
# is a multi-step interactive flow driven from the Settings UI (see
# core/main.py's /api/telegram/* routes), not something expressible as a
# single voice command. modules.messaging's existing
# messaging_watch_contact/messaging_reply/messaging_snooze already work
# unmodified once an account is connected and forwarding messages (see
# client_manager.py) — same "just a background service, no commands of its
# own" shape as modules.gmail.
