import { useEffect, useState } from "react";
import { getCredentialsStatus, updateCredentials } from "../../api/english";
import type { CredentialsStatus, CredentialsUpdate } from "../../api/english";
import { Dialog } from "./Dialog";

interface CredentialsDialogProps {
  onClose: () => void;
}

interface FieldSpec {
  key: keyof CredentialsUpdate;
  label: string;
  type: "password" | "text";
  configured: (status: CredentialsStatus) => boolean;
}

const FIELDS: FieldSpec[] = [
  { key: "tmdb_api_key", label: "TMDB API-ключ или токен", type: "password", configured: (status) => status.tmdb },
  {
    key: "opensubtitles_api_key",
    label: "OpenSubtitles API-ключ (consumer)",
    type: "password",
    configured: (status) => status.opensubtitles_api_key,
  },
  {
    key: "opensubtitles_username",
    label: "Логин OpenSubtitles",
    type: "text",
    configured: (status) => status.opensubtitles_account,
  },
  {
    key: "opensubtitles_password",
    label: "Пароль OpenSubtitles",
    type: "password",
    configured: (status) => status.opensubtitles_account,
  },
];

export function CredentialsDialog({ onClose }: CredentialsDialogProps): JSX.Element {
  const [status, setStatus] = useState<CredentialsStatus | null>(null);
  const [values, setValues] = useState<CredentialsUpdate>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getCredentialsStatus()
      .then(setStatus)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось загрузить статус."));
  }, []);

  async function save(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      const filled = Object.fromEntries(
        Object.entries(values).filter(([, value]) => typeof value === "string" && value.trim() !== ""),
      ) as CredentialsUpdate;
      setStatus(await updateCredentials(filled));
      setValues({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title="Источники субтитров" onClose={onClose}>
      <p className="ql-muted">
        Ключи хранятся только в системном хранилище секретов этого компьютера. TMDB — themoviedb.org → Settings → API.
        OpenSubtitles — opensubtitles.com → API consumers; для скачивания нужен ваш аккаунт (лимит скачиваний в день).
      </p>
      {FIELDS.map((field) => (
        <label key={field.key} className="ql-field">
          <span className="ql-field__label">
            {field.label}
            {status && (
              <span className={field.configured(status) ? "ql-badge ql-badge--good" : "ql-badge"}>
                {field.configured(status) ? "задан" : "нет"}
              </span>
            )}
          </span>
          <input
            className="ql-input"
            type={field.type}
            autoComplete="off"
            value={values[field.key] ?? ""}
            placeholder={status && field.configured(status) ? "Оставьте пустым, чтобы не менять" : ""}
            onChange={(event) => setValues({ ...values, [field.key]: event.target.value })}
          />
        </label>
      ))}
      {error && <p className="ql-error">{error}</p>}
      <div className="ql-row ql-row--end">
        <button type="button" className="ql-button ql-button--ghost" onClick={onClose}>
          Закрыть
        </button>
        <button
          type="button"
          className="ql-button ql-button--primary"
          onClick={() => void save()}
          disabled={busy || Object.values(values).every((value) => !value)}
        >
          Сохранить
        </button>
      </div>
    </Dialog>
  );
}
