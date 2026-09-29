import { useEffect, useState } from "react";
import {
  getPowerStatus,
  IDLE_TIMEOUT_MAX_S,
  IDLE_TIMEOUT_MIN_S,
  updatePowerSettings,
  type PowerMode,
  type PowerSettingsUpdate,
  type PowerStatus,
} from "../api/power";
import { usePolling } from "../hooks/usePolling";
import "./PowerSettingsPanel.css";

const STATUS_POLL_INTERVAL_MS = 5000;

const MODE_OPTIONS: ReadonlyArray<{ mode: PowerMode; label: string }> = [
  { mode: "auto", label: "Авто" },
  { mode: "always", label: "Всегда" },
  { mode: "off", label: "Выкл" },
];

const MODE_HINTS: Record<PowerMode, string> = {
  auto: "Экономия включается, когда ноутбук работает от батареи.",
  always: "Экономия включена всегда, даже от сети.",
  off: "Экономия выключена: ведёт себя как при работе от сети.",
};

interface TimeoutDrafts {
  battery: string;
  ac: string;
}

function parseTimeout(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  const parsed = Number(trimmed);
  return parsed >= IDLE_TIMEOUT_MIN_S && parsed <= IDLE_TIMEOUT_MAX_S ? parsed : null;
}

function draftsFrom(status: PowerStatus): TimeoutDrafts {
  return { battery: String(status.idle_timeout_battery_s), ac: String(status.idle_timeout_ac_s) };
}

function describeWorker(status: PowerStatus): string {
  if (!status.worker_running) {
    return "остановлен";
  }
  if (status.worker_device === "cuda") {
    return "запущен (видеокарта)";
  }
  if (status.worker_device === "cpu") {
    return "запущен (процессор)";
  }
  return "запущен";
}

export function PowerSettingsPanel(): JSX.Element {
  const [status, setStatus] = useState<PowerStatus | null>(null);
  const [drafts, setDrafts] = useState<TimeoutDrafts | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [autostart, setAutostart] = useState<boolean | null>(null);
  const [autostartBusy, setAutostartBusy] = useState(false);

  const autostartApi = window.assistantAPI;
  const autostartSupported = Boolean(autostartApi?.getAutostart && autostartApi.setAutostart);

  async function refresh(): Promise<void> {
    try {
      const next = await getPowerStatus();
      setStatus(next);
      setDrafts((current) => current ?? draftsFrom(next));
    } catch (err) {
      console.error("Failed to load power settings:", err);
      setError("Не удалось загрузить настройки питания.");
    }
  }

  usePolling(refresh, STATUS_POLL_INTERVAL_MS);

  useEffect(() => {
    const getAutostart = window.assistantAPI?.getAutostart;
    if (!getAutostart) {
      return;
    }
    let cancelled = false;
    getAutostart()
      .then((enabled: boolean) => {
        if (!cancelled) {
          setAutostart(enabled);
        }
      })
      .catch((err: unknown) => {
        console.error("Failed to read the autostart setting:", err);
        if (!cancelled) {
          setError("Не удалось узнать состояние автозапуска.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save(update: PowerSettingsUpdate, successNotice: string): Promise<void> {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await updatePowerSettings(update);
      setStatus(next);
      setDrafts(draftsFrom(next));
      setNotice(successNotice);
    } catch (err) {
      console.error("Failed to save power settings:", err);
      setError(err instanceof Error ? err.message : "Не удалось сохранить настройки питания.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAutostartChange(enabled: boolean): Promise<void> {
    const setter = window.assistantAPI?.setAutostart;
    if (!setter) {
      return;
    }
    setAutostartBusy(true);
    setError("");
    try {
      setAutostart(await setter(enabled));
    } catch (err) {
      console.error("Failed to change the autostart setting:", err);
      setError("Не удалось изменить автозапуск.");
    } finally {
      setAutostartBusy(false);
    }
  }

  const batteryTimeout = drafts ? parseTimeout(drafts.battery) : null;
  const acTimeout = drafts ? parseTimeout(drafts.ac) : null;
  const timeoutsValid = batteryTimeout !== null && acTimeout !== null;
  const timeoutsChanged =
    status !== null &&
    timeoutsValid &&
    (batteryTimeout !== status.idle_timeout_battery_s || acTimeout !== status.idle_timeout_ac_s);

  return (
    <div className="settings-panel__profile power-settings">
      {error && <p className="status-error">{error}</p>}
      {!status && !error && <p className="status-detail">Загрузка…</p>}

      {status && (
        <>
          <div className="settings-panel__field">
            <span className="settings-panel__label">Состояние</span>
            <dl className="power-settings__status">
              <dt>Питание</dt>
              <dd>{status.on_battery ? "от батареи" : "от сети"}</dd>
              <dt>Энергосбережение</dt>
              <dd className={status.saving_active ? "power-settings__on" : undefined}>
                {status.saving_active ? "активно" : "не активно"}
              </dd>
              <dt>Воркер нейросетей</dt>
              <dd>{describeWorker(status)}</dd>
            </dl>
          </div>

          <div className="settings-panel__field">
            <span className="settings-panel__label">Энергосбережение</span>
            <div className="row voice-lang-toggle" role="radiogroup" aria-label="Режим энергосбережения">
              {MODE_OPTIONS.map((option) => (
                <button
                  key={option.mode}
                  type="button"
                  role="radio"
                  aria-checked={status.mode === option.mode}
                  className={status.mode === option.mode ? "active" : ""}
                  disabled={saving}
                  onClick={() => {
                    if (status.mode !== option.mode) {
                      void save({ mode: option.mode }, "Режим сохранён.");
                    }
                  }}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="status-detail">{MODE_HINTS[status.mode]}</p>
          </div>

          <div className="settings-panel__field">
            <span className="settings-panel__label">Выгружать модели после простоя, секунд</span>
            <div className="power-settings__timeouts">
              <label className="power-settings__timeout">
                <span>При экономии</span>
                <input
                  type="number"
                  min={IDLE_TIMEOUT_MIN_S}
                  max={IDLE_TIMEOUT_MAX_S}
                  value={drafts?.battery ?? ""}
                  aria-invalid={batteryTimeout === null}
                  onChange={(event) => setDrafts((current) => ({ ac: current?.ac ?? "", battery: event.target.value }))}
                />
              </label>
              <label className="power-settings__timeout">
                <span>От сети</span>
                <input
                  type="number"
                  min={IDLE_TIMEOUT_MIN_S}
                  max={IDLE_TIMEOUT_MAX_S}
                  value={drafts?.ac ?? ""}
                  aria-invalid={acTimeout === null}
                  onChange={(event) => setDrafts((current) => ({ battery: current?.battery ?? "", ac: event.target.value }))}
                />
              </label>
            </div>
            {!timeoutsValid && (
              <p className="status-error">
                Допустимо от {IDLE_TIMEOUT_MIN_S} до {IDLE_TIMEOUT_MAX_S} секунд.
              </p>
            )}
            <div className="row">
              <button
                type="button"
                disabled={saving || !timeoutsChanged}
                onClick={() => {
                  if (batteryTimeout !== null && acTimeout !== null) {
                    void save(
                      { idle_timeout_battery_s: batteryTimeout, idle_timeout_ac_s: acTimeout },
                      "Таймауты сохранены.",
                    );
                  }
                }}
              >
                Сохранить
              </button>
            </div>
          </div>

          <div className="settings-panel__field">
            <label className="settings-panel__radio">
              <input
                type="checkbox"
                checked={status.gpu_on_battery}
                disabled={saving}
                onChange={(event) => void save({ gpu_on_battery: event.target.checked }, "Сохранено.")}
              />
              Использовать видеокарту на батарее
            </label>
          </div>
        </>
      )}

      {autostartSupported && (
        <div className="settings-panel__field">
          <label className="settings-panel__radio">
            <input
              type="checkbox"
              checked={autostart === true}
              disabled={autostart === null || autostartBusy}
              onChange={(event) => void handleAutostartChange(event.target.checked)}
            />
            Запускать при входе в систему
          </label>
        </div>
      )}

      {notice && <p className="settings-panel__success">{notice}</p>}
    </div>
  );
}
