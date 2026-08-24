import { Cake, Ruler, Scale, TrendingDown, TrendingUp, User } from "lucide-react";
import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getFitnessProfile, getFitnessWeightHistory, updateFitnessProfile } from "../api/client";
import type { FitnessBioProfile, FitnessSex, FitnessWeightHistoryEntry } from "../types";
import "./FitnessPanel.css";

// Neutral WHO BMI bands, same thresholds core/backend's
// modules.fitness_tracker.calculations.get_bmi_category uses — kept as
// plain numeric ranges here rather than duplicating category-label text,
// since the label itself already comes from the backend response
// (bmi_category) and this only draws the marker's position.
const BMI_MIN = 15;
const BMI_MAX = 40;
const BMI_BANDS: { upTo: number; label: string }[] = [
  { upTo: 18.5, label: "Дефицит" },
  { upTo: 25, label: "Норма" },
  { upTo: 30, label: "Избыток" },
  { upTo: BMI_MAX, label: "Ожирение" },
];

function StatTile({
  icon,
  label,
  value,
}: {
  icon: JSX.Element;
  label: string;
  value: string;
}): JSX.Element {
  return (
    <div className="fitness-stat-tile">
      <span className="fitness-stat-tile__icon">{icon}</span>
      <span className="fitness-stat-tile__value">{value}</span>
      <span className="fitness-stat-tile__label">{label}</span>
    </div>
  );
}

function BmiScale({ bmi, category }: { bmi: number; category: string | null }): JSX.Element {
  const clamped = Math.min(Math.max(bmi, BMI_MIN), BMI_MAX);
  const markerPercent = ((clamped - BMI_MIN) / (BMI_MAX - BMI_MIN)) * 100;
  let previousUpTo = BMI_MIN;

  return (
    <div className="fitness-panel__bmi-scale">
      <span className="fitness-panel__bmi-caption">Индекс массы тела (ИМТ)</span>
      <div className="fitness-panel__bmi-header">
        <span className="fitness-panel__bmi-number">{bmi.toFixed(1)}</span>
        {category && <span className="fitness-panel__bmi-chip">{category}</span>}
      </div>
      <div className="fitness-panel__bmi-track">
        {BMI_BANDS.map((band) => {
          const widthPercent = ((band.upTo - previousUpTo) / (BMI_MAX - BMI_MIN)) * 100;
          previousUpTo = band.upTo;
          return <div key={band.label} className="fitness-panel__bmi-band" style={{ width: `${widthPercent}%` }} />;
        })}
        <div className="fitness-panel__bmi-marker" style={{ left: `${markerPercent}%` }} title={`ИМТ ${bmi.toFixed(1)}`} />
      </div>
      <div className="fitness-panel__bmi-legend">
        {BMI_BANDS.map((band, index) => (
          <span key={band.label} className="fitness-panel__bmi-legend-item">
            <span className={`fitness-panel__bmi-legend-dot fitness-panel__bmi-legend-dot--${index}`} />
            {band.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function WeightChart({ history }: { history: FitnessWeightHistoryEntry[] }): JSX.Element | null {
  if (history.length < 2) {
    return null;
  }
  const data = history.map((entry) => ({
    date: new Date(entry.recorded_at).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }),
    weight: entry.weight_kg,
  }));
  const delta = data[data.length - 1].weight - data[data.length - 2].weight;

  return (
    <div className="fitness-panel__chart">
      <div className="fitness-panel__chart-header">
        <span className="fitness-panel__chart-title">Динамика веса</span>
        {Math.abs(delta) > 0.01 && (
          <span className={`fitness-panel__trend${delta > 0 ? " fitness-panel__trend--up" : " fitness-panel__trend--down"}`}>
            {delta > 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
            {Math.abs(delta).toFixed(1)} кг
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id="fitnessWeightFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent-green)" stopOpacity={0.45} />
              <stop offset="100%" stopColor="var(--accent-green)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="date" stroke="var(--text-dim)" fontSize={11} />
          <YAxis stroke="var(--text-dim)" fontSize={11} domain={["dataMin - 2", "dataMax + 2"]} />
          <Tooltip contentStyle={{ background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: 10 }} />
          <Area
            type="monotone"
            dataKey="weight"
            stroke="var(--accent-green)"
            strokeWidth={3}
            fill="url(#fitnessWeightFill)"
            dot={{ r: 3, fill: "var(--accent-green)" }}
            activeDot={{ r: 5 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FitnessPanel(): JSX.Element {
  const [profile, setProfile] = useState<FitnessBioProfile | null>(null);
  const [weightHistory, setWeightHistory] = useState<FitnessWeightHistoryEntry[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

  const [sex, setSex] = useState<FitnessSex | "">("");
  const [age, setAge] = useState("");
  const [heightCm, setHeightCm] = useState("");
  const [weightKg, setWeightKg] = useState("");

  async function refresh(): Promise<void> {
    try {
      const [loadedProfile, history] = await Promise.all([getFitnessProfile(), getFitnessWeightHistory()]);
      setProfile(loadedProfile);
      setWeightHistory(history);
      setSex(loadedProfile?.sex ?? "");
      setAge(loadedProfile?.age != null ? String(loadedProfile.age) : "");
      setHeightCm(loadedProfile?.height_cm != null ? String(loadedProfile.height_cm) : "");
      setWeightKg(loadedProfile?.weight_kg != null ? String(loadedProfile.weight_kg) : "");
      setError("");
    } catch (err) {
      console.error("Failed to load the fitness profile:", err);
      setError("Не удалось загрузить профиль.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleSave(): Promise<void> {
    setSaving(true);
    setError("");
    try {
      const updated = await updateFitnessProfile({
        sex: sex || null,
        age: age.trim() ? Number(age) : null,
        height_cm: heightCm.trim() ? Number(heightCm) : null,
        weight_kg: weightKg.trim() ? Number(weightKg) : null,
      });
      setProfile(updated);
      setWeightHistory(await getFitnessWeightHistory());
      setEditOpen(false);
    } catch (err) {
      console.error("Failed to save the fitness profile:", err);
      setError("Не удалось сохранить профиль.");
    } finally {
      setSaving(false);
    }
  }

  const sexLabel = profile?.sex === "male" ? "Муж." : profile?.sex === "female" ? "Жен." : "—";

  return (
    <div className="fitness-panel">
      <div className="fitness-panel__toolbar">
        <button type="button" className="fitness-panel__edit-toggle" onClick={() => setEditOpen((v) => !v)}>
          {editOpen ? "Скрыть" : "Изменить"}
        </button>
      </div>
      {error && <p className="status-error">{error}</p>}

      <div className="fitness-stat-row">
        <StatTile icon={<Scale size={20} />} label="Вес, кг" value={profile?.weight_kg != null ? `${profile.weight_kg}` : "—"} />
        <StatTile icon={<Ruler size={20} />} label="Рост, см" value={profile?.height_cm != null ? `${profile.height_cm}` : "—"} />
        <StatTile icon={<Cake size={20} />} label="Возраст" value={profile?.age != null ? `${profile.age}` : "—"} />
        <StatTile icon={<User size={20} />} label="Пол" value={sexLabel} />
      </div>

      {editOpen && (
        <div className="fitness-panel__edit-form">
          <div className="row">
            <select value={sex} onChange={(event) => setSex(event.target.value as FitnessSex | "")}>
              <option value="">Пол не указан</option>
              <option value="male">Мужской</option>
              <option value="female">Женский</option>
            </select>
            <input type="number" placeholder="Возраст" value={age} onChange={(event) => setAge(event.target.value)} />
          </div>
          <div className="row">
            <input
              type="number"
              placeholder="Рост, см"
              value={heightCm}
              onChange={(event) => setHeightCm(event.target.value)}
            />
            <input
              type="number"
              placeholder="Вес, кг"
              value={weightKg}
              onChange={(event) => setWeightKg(event.target.value)}
            />
          </div>
          <div className="row">
            <button type="button" onClick={() => void handleSave()} disabled={saving}>
              {saving ? "Сохраняю…" : "Сохранить"}
            </button>
          </div>
        </div>
      )}

      {profile?.bmi != null && <BmiScale bmi={profile.bmi} category={profile.bmi_category} />}
      <WeightChart history={weightHistory} />
    </div>
  );
}
