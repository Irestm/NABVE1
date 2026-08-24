import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip } from "recharts";
import { addFitnessMeasurement, listFitnessMeasurements } from "../api/client";
import type { FitnessMeasurement } from "../types";
import "./FitnessMeasurementsSection.css";

// Cycled by group position, same convention as CommandPanel's ACCENT_CYCLE —
// body parts are a fixed backend-defined list (see BODY_PARTS below), but
// only the parts the user actually has data for get rendered as a card, so
// a fixed part->color table would leave gaps whenever some parts are unused.
const ACCENT_CYCLE = [
  "var(--accent-green)",
  "var(--accent-blue)",
  "var(--accent-purple)",
  "var(--accent-amber)",
  "var(--accent-red)",
  "var(--glow-listening)",
];

const BODY_PARTS: { value: string; label: string }[] = [
  { value: "bicep", label: "Бицепс" },
  { value: "waist", label: "Талия" },
  { value: "chest", label: "Грудь" },
  { value: "thigh", label: "Бедро" },
  { value: "shoulder", label: "Плечо" },
  { value: "calf", label: "Икра" },
];

function bodyPartLabel(value: string): string {
  return BODY_PARTS.find((part) => part.value === value)?.label ?? value;
}

function groupByBodyPart(measurements: FitnessMeasurement[]): Map<string, FitnessMeasurement[]> {
  const groups = new Map<string, FitnessMeasurement[]>();
  for (const measurement of measurements) {
    const list = groups.get(measurement.body_part) ?? [];
    list.push(measurement);
    groups.set(measurement.body_part, list);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
  }
  return groups;
}

export function FitnessMeasurementsSection(): JSX.Element {
  const [measurements, setMeasurements] = useState<FitnessMeasurement[]>([]);
  const [error, setError] = useState("");
  const [bodyPart, setBodyPart] = useState(BODY_PARTS[0].value);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  async function refresh(): Promise<void> {
    try {
      setMeasurements(await listFitnessMeasurements());
      setError("");
    } catch (err) {
      console.error("Failed to load measurements:", err);
      setError("Не удалось загрузить замеры.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleAdd(): Promise<void> {
    const parsed = Number(value);
    if (!value.trim() || Number.isNaN(parsed)) {
      return;
    }
    setSaving(true);
    try {
      await addFitnessMeasurement(bodyPart, parsed);
      setValue("");
      await refresh();
    } catch (err) {
      console.error("Failed to add a measurement:", err);
      setError("Не удалось сохранить замер.");
    } finally {
      setSaving(false);
    }
  }

  const groups = groupByBodyPart(measurements);

  return (
    <div className="fitness-measurements">
      {error && <p className="status-error">{error}</p>}

      <div className="row">
        <select value={bodyPart} onChange={(event) => setBodyPart(event.target.value)}>
          {BODY_PARTS.map((part) => (
            <option key={part.value} value={part.value}>
              {part.label}
            </option>
          ))}
        </select>
        <input type="number" placeholder="см" value={value} onChange={(event) => setValue(event.target.value)} />
        <button type="button" onClick={() => void handleAdd()} disabled={saving}>
          {saving ? "…" : "Добавить"}
        </button>
      </div>

      <div className="fitness-measurements__grid">
        {[...groups.entries()].map(([part, entries], index) => {
          const accent = ACCENT_CYCLE[index % ACCENT_CYCLE.length];
          const latest = entries[entries.length - 1];
          const previous = entries.length >= 2 ? entries[entries.length - 2] : null;
          const delta = previous ? latest.value_cm - previous.value_cm : null;
          return (
            <div key={part} className="fitness-measurements__card" style={{ "--item-accent": accent } as CSSProperties}>
              <div className="fitness-measurements__card-header">
                <span className="fitness-measurements__card-label">{bodyPartLabel(part)}</span>
                {delta != null && Math.abs(delta) > 0.01 && (
                  <span className="fitness-measurements__card-delta">
                    {delta > 0 ? "+" : ""}
                    {delta.toFixed(1)} см
                  </span>
                )}
              </div>
              <span className="fitness-measurements__card-value">{latest.value_cm} см</span>
              {entries.length >= 2 && (
                <ResponsiveContainer width="100%" height={44}>
                  <LineChart data={entries.map((entry) => ({ value: entry.value_cm }))}>
                    <Tooltip contentStyle={{ background: "var(--bg-elevated)", border: "1px solid var(--border)" }} />
                    <Line type="monotone" dataKey="value" stroke={accent} strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
