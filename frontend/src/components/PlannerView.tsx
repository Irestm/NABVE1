import { useEffect, useMemo, useState } from "react";
import { createCalendarEvent, deleteCalendarEvent, listUpcomingEvents } from "../api/client";
import type { CalendarEvent } from "../types";
import "./PlannerView.css";

const WEEKDAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MONTH_LABELS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const POLL_INTERVAL_MS = 30000;

interface MonthCell {
  day: number;
  dateKey: string;
  inCurrentMonth: boolean;
}

function pad2(value: number): string {
  return value.toString().padStart(2, "0");
}

function dateKeyOf(year: number, month: number, day: number): string {
  return `${year}-${pad2(month + 1)}-${pad2(day)}`;
}

function toDateKey(isoDateTime: string): string {
  return isoDateTime.slice(0, 10);
}

function formatEventTime(isoDateTime: string): string {
  const [datePart, timePart] = isoDateTime.split("T");
  const [year, month, day] = datePart.split("-");
  return `${day}.${month}.${year} ${timePart?.slice(0, 5) ?? ""}`;
}

function formatDateKeyRu(dateKey: string): string {
  return dateKey.split("-").reverse().join(".");
}

// Backend stores/reads event_time as a naive local ISO-8601 string (see
// modules/calendar/handlers.py: datetime.fromisoformat) — concatenating the
// <input type="date">/<input type="time"> values directly avoids any
// JS Date/timezone round-trip that could shift the time the user actually
// picked.
function toEventTimeIso(dateKey: string, time: string): string {
  return `${dateKey}T${time}:00`;
}

function buildMonthGrid(year: number, month: number): MonthCell[] {
  const firstOfMonth = new Date(year, month, 1);
  // getDay(): 0=Sunday..6=Saturday - shift to Monday-first (0=Mon..6=Sun).
  const firstWeekday = (firstOfMonth.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrevMonth = new Date(year, month, 0).getDate();
  const prevMonth = month === 0 ? 11 : month - 1;
  const prevYear = month === 0 ? year - 1 : year;
  const nextMonth = month === 11 ? 0 : month + 1;
  const nextYear = month === 11 ? year + 1 : year;

  const cells: MonthCell[] = [];
  for (let i = firstWeekday - 1; i >= 0; i--) {
    const day = daysInPrevMonth - i;
    cells.push({ day, dateKey: dateKeyOf(prevYear, prevMonth, day), inCurrentMonth: false });
  }
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ day, dateKey: dateKeyOf(year, month, day), inCurrentMonth: true });
  }
  let trailingDay = 1;
  while (cells.length % 7 !== 0) {
    cells.push({ day: trailingDay, dateKey: dateKeyOf(nextYear, nextMonth, trailingDay), inCurrentMonth: false });
    trailingDay += 1;
  }
  return cells;
}

export function PlannerView(): JSX.Element {
  const today = useMemo(() => new Date(), []);
  const todayKey = dateKeyOf(today.getFullYear(), today.getMonth(), today.getDate());

  const [viewYear, setViewYear] = useState(today.getFullYear());
  const [viewMonth, setViewMonth] = useState(today.getMonth());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [error, setError] = useState("");
  const [selectedDateKey, setSelectedDateKey] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [date, setDate] = useState(todayKey);
  const [time, setTime] = useState("09:00");
  const [remindBefore, setRemindBefore] = useState(30);
  const [submitting, setSubmitting] = useState(false);

  async function refresh(): Promise<void> {
    try {
      const result = await listUpcomingEvents();
      setEvents(result);
      setError("");
    } catch (error) {
      console.error("Failed to load upcoming events:", error);
      setError("Не удалось загрузить события");
    }
  }

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  const eventsByDate = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const event of events) {
      const key = toDateKey(event.event_time);
      const list = map.get(key) ?? [];
      list.push(event);
      map.set(key, list);
    }
    return map;
  }, [events]);

  const cells = useMemo(() => buildMonthGrid(viewYear, viewMonth), [viewYear, viewMonth]);

  function goToPrevMonth(): void {
    if (viewMonth === 0) {
      setViewYear((year) => year - 1);
      setViewMonth(11);
    } else {
      setViewMonth((month) => month - 1);
    }
  }

  function goToNextMonth(): void {
    if (viewMonth === 11) {
      setViewYear((year) => year + 1);
      setViewMonth(0);
    } else {
      setViewMonth((month) => month + 1);
    }
  }

  function handleSelectDay(cell: MonthCell): void {
    setSelectedDateKey((current) => (current === cell.dateKey ? null : cell.dateKey));
    setDate(cell.dateKey);
  }

  async function handleCreate(): Promise<void> {
    if (!title.trim() || !date || !time) {
      return;
    }
    setSubmitting(true);
    try {
      await createCalendarEvent(title.trim(), toEventTimeIso(date, time), remindBefore);
      setTitle("");
      await refresh();
    } catch (error) {
      console.error("Failed to create a calendar event:", error);
      setError("Не удалось создать событие");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(eventId: number): Promise<void> {
    try {
      await deleteCalendarEvent(eventId);
      await refresh();
    } catch (error) {
      console.error("Failed to delete a calendar event:", error);
      setError("Не удалось удалить событие");
    }
  }

  const visibleEvents = selectedDateKey ? eventsByDate.get(selectedDateKey) ?? [] : events;

  return (
    <div className="planner">
      <div className="planner__calendar">
        <div className="planner__month-nav">
          <button onClick={goToPrevMonth}>‹</button>
          <span className="planner__month-label">
            {MONTH_LABELS[viewMonth]} {viewYear}
          </span>
          <button onClick={goToNextMonth}>›</button>
        </div>

        <div className="planner__weekdays">
          {WEEKDAY_LABELS.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>

        <div className="planner__grid">
          {cells.map((cell) => {
            const dayEvents = eventsByDate.get(cell.dateKey) ?? [];
            const classNames = [
              "planner__day",
              cell.inCurrentMonth ? "" : "planner__day--outside",
              cell.dateKey === todayKey ? "planner__day--today" : "",
              cell.dateKey === selectedDateKey ? "planner__day--selected" : "",
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <button key={cell.dateKey} className={classNames} onClick={() => handleSelectDay(cell)}>
                <span>{cell.day}</span>
                {dayEvents.length > 0 && <span className="planner__day-dot" />}
              </button>
            );
          })}
        </div>
      </div>

      {error && <p className="status-error">{error}</p>}

      <div className="section">
        <h3>Новое событие</h3>
        <div className="planner__form">
          <input
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Что нужно сделать"
          />
          <div className="row">
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
            <input type="time" value={time} onChange={(event) => setTime(event.target.value)} />
          </div>
          <div className="row">
            <input
              type="number"
              min={0}
              value={remindBefore}
              onChange={(event) => setRemindBefore(Number(event.target.value))}
              title="Напомнить за, минут"
            />
            <button disabled={submitting} onClick={() => void handleCreate()}>
              Добавить
            </button>
          </div>
        </div>
      </div>

      <div className="section">
        <h3>{selectedDateKey ? `События на ${formatDateKeyRu(selectedDateKey)}` : "Ближайшие события"}</h3>
        {selectedDateKey && (
          <button className="planner__clear-filter" onClick={() => setSelectedDateKey(null)}>
            Показать все ближайшие
          </button>
        )}
        <div className="planner__events">
          {visibleEvents.length === 0 && <p className="last-message">Событий нет.</p>}
          {visibleEvents.map((event) => (
            <div key={event.id} className="planner__event-card">
              <div className="planner__event-info">
                <span className="planner__event-title">{event.title}</span>
                <span className="planner__event-time">
                  {formatEventTime(event.event_time)}
                  {event.remind_before_minutes > 0 ? ` · напомнить за ${event.remind_before_minutes} мин` : ""}
                </span>
              </div>
              <button className="danger" onClick={() => void handleDelete(event.id)}>
                Удалить
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
