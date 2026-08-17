# Jarvis Voice Control — Figma plugin

Figma-side counterpart to `modules/figma_control` on the Jarvis backend.
Lets voice commands ("создай прямоугольник 100 на 200", "выдели слой Кнопка",
"покрась в красный"...) act directly on the current Figma document via the
Plugin API, with `modules/figma_control/screen_fallback.py` covering
anything the API can't reach.

## One-time setup

1. Install dependencies and compile `code.ts` -> `code.js`:

   ```
   npm install
   npm run build
   ```

2. Open `ui.html` and set `WS_TOKEN` to the Jarvis backend's API token —
   found in `data/api_token.txt` next to the running backend (or the
   `ASSISTANT_API_TOKEN` env var, if you set one explicitly). If the backend
   isn't running on the default port 8756 (`ASSISTANT_PORT`), also update
   `WS_PORT` here and the `ws://127.0.0.1:<port>` entries in
   `manifest.json`'s `networkAccess.allowedDomains`.

3. In Figma Desktop: **Plugins -> Development -> Import plugin from
   manifest...** and pick this directory's `manifest.json`.

4. Run the plugin (**Plugins -> Development -> Jarvis Voice Control**) once
   per Figma session — it connects to the backend in the background (no
   visible UI) and stays connected until Figma or the plugin is closed.

Re-run `npm run build` after editing `code.ts`; Figma reloads `code.js` the
next time the plugin runs.

## How it fits together

- `code.ts` — the plugin's sandboxed main thread. Owns every `figma.*` call
  (create/move/resize/select/delete layers, grouping, alignment, export).
  Has no network access of its own.
- `ui.html` — a hidden UI iframe (a real browser context) that owns the
  actual `WebSocket` connection to the backend and relays raw JSON both
  ways via `postMessage`. Reconnects automatically if the backend restarts.
- The backend (`modules/figma_control/ws_server.py`) sends
  `{"request_id", "action", "params"}`; this plugin replies with
  `{"request_id", "status": "success"|"error"|"unsupported", "message", "result"}`.
  `"unsupported"` (e.g. `undo`/`redo`, which the Plugin API doesn't expose)
  tells the backend to fall back to `screen_fallback.py`.
