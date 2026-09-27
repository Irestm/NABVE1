import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Clapperboard, FileUp, Link2, Sparkles, Tv } from "lucide-react";
import { importFromLink, importSrt } from "../../api/english";
import type { ImportedEpisode, LinkImportRequest, NeedsInput, ShowOption, TitleKind } from "../../api/english";

interface ImportPanelProps {
  onImported: (imported: ImportedEpisode) => void;
}

interface Details {
  title: string;
  kind: TitleKind;
  season: string;
  episode: string;
  year: string;
  split: boolean;
  partMinutes: number;
}

type Tab = "link" | "file";

const EMPTY_DETAILS: Details = { title: "", kind: "series", season: "", episode: "", year: "", split: true, partMinutes: 20 };
const MIN_PART = 10;
const MAX_PART = 40;

function toNumber(value: string): number | null {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function OptionCard({ option, onPick, disabled }: { option: ShowOption; onPick: () => void; disabled: boolean }): JSX.Element {
  return (
    <button type="button" className="ql-option ql-title-option" onClick={onPick} disabled={disabled}>
      {option.poster_url ? (
        <img className="ql-title-option__poster" src={option.poster_url} alt="" loading="lazy" />
      ) : (
        <span className="ql-title-option__poster ql-title-option__poster--empty" aria-hidden="true">
          {option.kind === "movie" ? <Clapperboard size={22} /> : <Tv size={22} />}
        </span>
      )}
      <span className="ql-title-option__text">
        <span>{option.name}</span>
        <span className="ql-muted">
          {option.kind === "movie" ? "фильм" : "сериал"}
          {option.year ? ` · ${option.year}` : ""}
        </span>
      </span>
    </button>
  );
}

export function ImportPanel({ onImported }: ImportPanelProps): JSX.Element {
  const [tab, setTab] = useState<Tab>("link");
  const [url, setUrl] = useState("");
  const [request, setRequest] = useState<LinkImportRequest | null>(null);
  const [needs, setNeeds] = useState<NeedsInput | null>(null);
  const [details, setDetails] = useState<Details>(EMPTY_DETAILS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  function reset(): void {
    setNeeds(null);
    setRequest(null);
    setError("");
  }

  function movieOptions(base: LinkImportRequest): LinkImportRequest {
    return { ...base, split_movie: details.split, part_minutes: details.partMinutes };
  }

  async function run(next: LinkImportRequest): Promise<void> {
    setBusy(true);
    setError("");
    setRequest(next);
    try {
      const result = await importFromLink(movieOptions(next));
      if (result.status === "imported" && result.imported) {
        reset();
        setUrl("");
        onImported(result.imported);
      } else if (result.needs_input) {
        const guess = result.needs_input.guess;
        setNeeds(result.needs_input);
        setDetails((current) => ({
          ...current,
          title: guess.series_title ?? "",
          kind: guess.kind ?? current.kind,
          season: guess.season !== null ? String(guess.season) : "",
          episode: guess.episode !== null ? String(guess.episode) : "",
          year: guess.year !== null ? String(guess.year) : "",
        }));
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
    const year = toNumber(details.year);
    return {
      ...base,
      kind: details.kind,
      ...(details.title.trim() ? { series_title: details.title.trim() } : {}),
      ...(details.kind === "series" && season !== null ? { season } : {}),
      ...(details.kind === "series" && episode !== null ? { episode } : {}),
      ...(details.kind === "movie" && year !== null ? { year } : {}),
    };
  }

  async function uploadFile(file: File): Promise<void> {
    const season = toNumber(details.season);
    const episode = toNumber(details.episode);
    const year = toNumber(details.year);
    if (!details.title.trim()) {
      setError(details.kind === "movie" ? "Укажите название фильма." : "Укажите сериал.");
      return;
    }
    if (details.kind === "series" && (season === null || episode === null)) {
      setError("Укажите сезон и серию.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const imported = await importSrt(
        {
          title: details.title.trim(),
          kind: details.kind,
          ...(details.kind === "series" && season !== null && episode !== null ? { season, episode } : {}),
          ...(details.kind === "movie"
            ? { splitMovie: details.split, partMinutes: details.partMinutes, ...(year !== null ? { year } : {}) }
            : {}),
        },
        file,
      );
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

  const kindSwitch = (
    <div className="ql-segmented" role="group" aria-label="Что импортируем">
      {(["series", "movie"] as TitleKind[]).map((kind) => (
        <button
          key={kind}
          type="button"
          className={details.kind === kind ? "ql-segmented__item ql-segmented__item--active" : "ql-segmented__item"}
          aria-pressed={details.kind === kind}
          onClick={() => setDetails({ ...details, kind })}
        >
          {kind === "series" ? <Tv size={16} /> : <Clapperboard size={16} />} {kind === "series" ? "Сериал" : "Фильм"}
        </button>
      ))}
    </div>
  );

  const detailsFields = (
    <>
      {kindSwitch}
      <div className="ql-details">
        <label className="ql-field ql-details__title">
          <span className="ql-field__label">{details.kind === "movie" ? "Фильм" : "Сериал"}</span>
          <input
            className="ql-input"
            value={details.title}
            onChange={(event) => setDetails({ ...details, title: event.target.value })}
            placeholder={details.kind === "movie" ? "Sherlock Holmes" : "Breaking Bad"}
          />
        </label>
        {details.kind === "series" ? (
          <>
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
          </>
        ) : (
          <label className="ql-field">
            <span className="ql-field__label">Год</span>
            <input
              className="ql-input"
              inputMode="numeric"
              value={details.year}
              onChange={(event) => setDetails({ ...details, year: event.target.value })}
              placeholder="2009"
            />
          </label>
        )}
      </div>
    </>
  );

  const movieSplit = (
    <div className="ql-split-row">
      <label className="ql-check">
        <input
          type="checkbox"
          checked={details.split}
          onChange={(event) => setDetails({ ...details, split: event.target.checked })}
        />
        <span>Разбить фильм на части</span>
      </label>
      {details.split && (
        <label className="ql-check">
          <span>по</span>
          <input
            className="ql-input ql-input--narrow"
            type="number"
            min={MIN_PART}
            max={MAX_PART}
            value={details.partMinutes}
            onChange={(event) =>
              setDetails({
                ...details,
                partMinutes: Math.min(MAX_PART, Math.max(MIN_PART, Number(event.target.value) || MIN_PART)),
              })
            }
            aria-label="Длительность части в минутах"
          />
          <span>мин</span>
        </label>
      )}
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
    <section className="ql-card ql-import" aria-label="Добавить серию или фильм">
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
              placeholder="Ссылка на серию или фильм: YouTube, стриминг, IMDb…"
              disabled={busy}
            />
            <button type="submit" className="ql-button ql-button--primary" disabled={busy || !url.trim()}>
              {busy ? "Ищу…" : "Создать квиз"}
            </button>
          </form>
          {movieSplit}

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

              {(needs.kind === "series" || needs.kind === "title") && (
                <div className="ql-options__grid">
                  {needs.options.map((option) => (
                    <OptionCard
                      key={`${option.kind}-${option.tmdb_id}`}
                      option={option}
                      disabled={busy}
                      onPick={() =>
                        void run({
                          ...request,
                          tmdb_id: option.tmdb_id,
                          kind: option.kind,
                          series_title: option.name,
                          ...(option.year ? { year: option.year } : {}),
                        })
                      }
                    />
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
          {details.kind === "movie" && movieSplit}
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
