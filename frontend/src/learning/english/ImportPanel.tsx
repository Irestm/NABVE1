import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { FileUp, Link2, Sparkles } from "lucide-react";
import { importFromLink, importSrt } from "../../api/english";
import type { ImportedEpisode, LinkImportRequest, NeedsInput } from "../../api/english";

interface ImportPanelProps {
  onImported: (imported: ImportedEpisode) => void;
}

interface Details {
  seriesTitle: string;
  season: string;
  episode: string;
}

type Tab = "link" | "file";

function toNumber(value: string): number | null {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function ImportPanel({ onImported }: ImportPanelProps): JSX.Element {
  const [tab, setTab] = useState<Tab>("link");
  const [url, setUrl] = useState("");
  const [request, setRequest] = useState<LinkImportRequest | null>(null);
  const [needs, setNeeds] = useState<NeedsInput | null>(null);
  const [details, setDetails] = useState<Details>({ seriesTitle: "", season: "", episode: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  function reset(): void {
    setNeeds(null);
    setRequest(null);
    setError("");
  }

  async function run(next: LinkImportRequest): Promise<void> {
    setBusy(true);
    setError("");
    setRequest(next);
    try {
      const result = await importFromLink(next);
      if (result.status === "imported" && result.imported) {
        reset();
        setUrl("");
        onImported(result.imported);
      } else if (result.needs_input) {
        const guess = result.needs_input.guess;
        setNeeds(result.needs_input);
        setDetails({
          seriesTitle: guess.series_title ?? "",
          season: guess.season !== null ? String(guess.season) : "",
          episode: guess.episode !== null ? String(guess.episode) : "",
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось импортировать.");
    } finally {
      setBusy(false);
    }
  }

  function submitLink(event: FormEvent): void {
    event.preventDefault();
    if (url.trim()) {
      setNeeds(null);
      void run({ url: url.trim() });
    }
  }

  function withDetails(base: LinkImportRequest): LinkImportRequest {
    const season = toNumber(details.season);
    const episode = toNumber(details.episode);
    return {
      ...base,
      ...(details.seriesTitle.trim() ? { series_title: details.seriesTitle.trim() } : {}),
      ...(season !== null ? { season } : {}),
      ...(episode !== null ? { episode } : {}),
    };
  }

  async function uploadFile(file: File): Promise<void> {
    const season = toNumber(details.season);
    const episode = toNumber(details.episode);
    if (!details.seriesTitle.trim() || season === null || episode === null) {
      setError("Укажите сериал, сезон и серию.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const imported = await importSrt(details.seriesTitle.trim(), season, episode, file);
      reset();
      onImported(imported);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить файл.");
    } finally {
      setBusy(false);
      if (fileRef.current) {
        fileRef.current.value = "";
      }
    }
  }

  const detailsFields = (
    <div className="ql-details">
      <label className="ql-field ql-details__title">
        <span className="ql-field__label">Сериал</span>
        <input
          className="ql-input"
          value={details.seriesTitle}
          onChange={(event) => setDetails({ ...details, seriesTitle: event.target.value })}
          placeholder="Breaking Bad"
        />
      </label>
      <label className="ql-field">
        <span className="ql-field__label">Сезон</span>
        <input
          className="ql-input"
          inputMode="numeric"
          value={details.season}
          onChange={(event) => setDetails({ ...details, season: event.target.value })}
          placeholder="1"
        />
      </label>
      <label className="ql-field">
        <span className="ql-field__label">Серия</span>
        <input
          className="ql-input"
          inputMode="numeric"
          value={details.episode}
          onChange={(event) => setDetails({ ...details, episode: event.target.value })}
          placeholder="1"
        />
      </label>
    </div>
  );

  const hiddenFileInput = (
    <input
      ref={fileRef}
      type="file"
      accept=".srt,.vtt,text/plain,application/x-subrip"
      hidden
      onChange={(event) => {
        const file = event.target.files?.[0];
        if (file) {
          void uploadFile(file);
        }
      }}
    />
  );

  return (
    <section className="ql-card ql-import" aria-label="Добавить эпизод">
      <div className="ql-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "link"}
          className={tab === "link" ? "ql-tabs__tab ql-tabs__tab--active" : "ql-tabs__tab"}
          onClick={() => setTab("link")}
        >
          <Link2 size={16} /> По ссылке
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "file"}
          className={tab === "file" ? "ql-tabs__tab ql-tabs__tab--active" : "ql-tabs__tab"}
          onClick={() => {
            setTab("file");
            reset();
          }}
        >
          <FileUp size={16} /> Файл .srt
        </button>
      </div>

      {tab === "link" ? (
        <>
          <form className="ql-input-row" onSubmit={submitLink}>
            <input
              className="ql-input"
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="Ссылка на серию: YouTube, стриминг, сайт с сериалом…"
              disabled={busy}
            />
            <button type="submit" className="ql-button ql-button--primary" disabled={busy || !url.trim()}>
              {busy ? "Ищу…" : "Создать квиз"}
            </button>
          </form>

          {needs && request && (
            <div className="ql-needs">
              <p className="ql-needs__message">{needs.message}</p>

              {needs.kind === "details" && (
                <>
                  {detailsFields}
                  {needs.alternatives.length > 0 && (
                    <p className="ql-muted">Возможно: {needs.alternatives.join(", ")}</p>
                  )}
                  <button
                    type="button"
                    className="ql-button ql-button--primary"
                    onClick={() => void run(withDetails(request))}
                    disabled={busy}
                  >
                    Продолжить
                  </button>
                </>
              )}

              {needs.kind === "series" && (
                <div className="ql-options__grid">
                  {needs.options.map((option) => (
                    <button
                      key={option.tmdb_id}
                      type="button"
                      className="ql-option"
                      onClick={() => void run({ ...request, tmdb_id: option.tmdb_id })}
                      disabled={busy}
                    >
                      <span>{option.name}</span>
                      {option.year && <span className="ql-muted">{option.year}</span>}
                    </button>
                  ))}
                </div>
              )}

              {needs.kind === "subtitles" && (
                <>
                  {needs.problems.length > 0 && (
                    <ul className="ql-problems">
                      {needs.problems.map((problem) => (
                        <li key={problem}>{problem}</li>
                      ))}
                    </ul>
                  )}
                  {detailsFields}
                  <div className="ql-row">
                    <button
                      type="button"
                      className="ql-button ql-button--primary"
                      onClick={() => fileRef.current?.click()}
                      disabled={busy}
                    >
                      <FileUp size={18} /> Загрузить .srt
                    </button>
                    <button
                      type="button"
                      className="ql-button ql-button--ghost"
                      onClick={() => void run({ ...withDetails(request), allow_ai_guess: true })}
                      disabled={busy}
                    >
                      <Sparkles size={18} /> Примерный вариант от ИИ
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </>
      ) : (
        <>
          {detailsFields}
          <button
            type="button"
            className="ql-button ql-button--primary"
            onClick={() => fileRef.current?.click()}
            disabled={busy}
          >
            <FileUp size={18} /> {busy ? "Обрабатываю…" : "Выбрать файл .srt"}
          </button>
        </>
      )}
      {hiddenFileInput}
      {error && <p className="ql-error">{error}</p>}
    </section>
  );
}
