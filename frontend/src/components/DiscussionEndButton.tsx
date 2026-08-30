import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { MessagesSquare, X } from "lucide-react";
import { getStatus, runCommand } from "../api/client";
import "./DiscussionEndButton.css";

const POLL_INTERVAL_MS = 2000;

interface DiscussionEndButtonProps {
  accent: string;
}

// Shown in the "Режимы" group only while discussion mode is running: a
// single "Закончить дискуссию" button (the mode is otherwise entered by the
// "Режим дискуссии" command button / voice and left by the exit phrase).
export function DiscussionEndButton({ accent }: DiscussionEndButtonProps): JSX.Element | null {
  const [active, setActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  async function refresh(): Promise<void> {
    try {
      const status = await getStatus();
      setActive(status.state === "discussion");
    } catch (err) {
      console.error("DiscussionEndButton status poll failed:", err);
    }
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      if (!busyRef.current) void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, []);

  if (!active) {
    return null;
  }

  const style = { "--item-accent": accent } as CSSProperties;

  return (
    <div className="discussion-end" style={style}>
      <div className="discussion-end__header">
        <MessagesSquare size={18} />
        <span className="discussion-end__title">Режим дискуссии</span>
        <span className="discussion-end__badge">идёт</span>
      </div>
      <button
        type="button"
        className="discussion-end__button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          busyRef.current = true;
          try {
            await runCommand("discussion_stop");
          } catch (err) {
            console.error("discussion_stop failed:", err);
          } finally {
            setBusy(false);
            busyRef.current = false;
            await refresh();
          }
        }}
      >
        <X size={15} />
        Закончить дискуссию
      </button>
    </div>
  );
}
