import { useEffect, useState } from "react";
import { cancelDelayedTask, listDelayedTasks } from "../api/client";
import type { DelayedTask } from "../types";
import "./DelayedTasksPanel.css";

const POLL_INTERVAL_MS = 15000;

function formatRunAt(iso: string): string {
  const [datePart, timePart] = iso.split("T");
  const [, month, day] = datePart.split("-");
  return `${day}.${month} ${timePart?.slice(0, 5) ?? ""}`;
}

export function DelayedTasksPanel() {
  const [tasks, setTasks] = useState<DelayedTask[]>([]);
  const [error, setError] = useState("");

  async function refresh(): Promise<void> {
    try {
      setTasks(await listDelayedTasks());
      setError("");
    } catch (err) {
      console.error("Failed to load delayed tasks:", err);
      setError("Не удалось загрузить отложенные задачи");
    }
  }

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  async function onCancel(taskId: number): Promise<void> {
    try {
      await cancelDelayedTask(taskId);
    } catch (err) {
      console.error("Failed to cancel delayed task:", err);
    }
    void refresh();
  }

  return (
    <div className="delayed-tasks">
      <h3 className="delayed-tasks__heading">Отложенные задачи</h3>
      {error && <p className="delayed-tasks__error">{error}</p>}
      {!error && tasks.length === 0 && (
        <p className="delayed-tasks__empty">Ничего не запланировано на потом.</p>
      )}
      <ul className="delayed-tasks__list">
        {tasks.map((task) => (
          <li className="delayed-tasks__item" key={task.id}>
            <div className="delayed-tasks__info">
              <span className="delayed-tasks__text">{task.original_text}</span>
              <span className="delayed-tasks__when">{formatRunAt(task.run_at)}</span>
            </div>
            <button
              className="delayed-tasks__cancel"
              onClick={() => void onCancel(task.id)}
              type="button"
            >
              Отменить
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
