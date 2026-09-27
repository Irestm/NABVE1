#!/usr/bin/env bash
set -euo pipefail

mkdir -p data logs

port="${ASSISTANT_PORT:-8756}"
token="$(python -c 'from core.config import settings; print(settings.api_token)')"

cat <<BANNER
────────────────────────────────────────────────────────────
 NABVE запускается в Docker
 Веб-интерфейс:  http://127.0.0.1:${port}/?token=${token}
 Токен сохранится в браузере — дальше хватит http://127.0.0.1:${port}/
────────────────────────────────────────────────────────────
BANNER

exec "$@"
