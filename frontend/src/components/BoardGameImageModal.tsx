import { useEffect, useState } from "react";
import { getImageRequest } from "../api/client";
import "./BoardGameImageModal.css";

const POLL_INTERVAL_MS = 1500;

// Shows the chess/draughts board SVG that core/voice/pipeline.py's
// _resolve_board_game posts via StateManager.request_image at the end of a
// voice game — see core/state.py::StateManager and GET /api/ui/image_request.
export function BoardGameImageModal(): JSX.Element | null {
  const [svg, setSvg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll(): Promise<void> {
      try {
        const response = await getImageRequest();
        if (!cancelled && response.svg) {
          setSvg(response.svg);
        }
      } catch (error) {
        // Backend not reachable this tick — just retry next poll.
        console.error("Failed to poll /api/ui/image_request:", error);
      }
    }

    const interval = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  if (!svg) {
    return null;
  }

  return (
    <div className="board-game-overlay">
      <div className="board-game-overlay__backdrop" onClick={() => setSvg(null)} />
      <div className="board-game-panel">
        <button
          type="button"
          className="board-game-panel__close"
          onClick={() => setSvg(null)}
          aria-label="Закрыть"
        >
          ✕
        </button>
        {/* svg is generated locally by chess.svg.board()/draughts.svg.board()
            (see modules/board_games) — never user- or network-supplied text,
            so rendering it directly is safe. */}
        <div className="board-game-panel__board" dangerouslySetInnerHTML={{ __html: svg }} />
      </div>
    </div>
  );
}
