import { useState } from "react";
import { ChevronDown, ChevronRight, Folder, KeyRound, TriangleAlert } from "lucide-react";
import type { EnglishEpisode, EnglishLibrary, EnglishSeries, ImportedEpisode } from "../../api/english";
import { CredentialsDialog } from "./CredentialsDialog";
import { ImportPanel } from "./ImportPanel";

interface LibraryViewProps {
  library: EnglishLibrary | null;
  error: string;
  onOpen: (series: EnglishSeries, episode: EnglishEpisode) => void;
  onImported: (imported: ImportedEpisode) => void;
}

function SeriesFolder({
  series,
  onOpen,
}: {
  series: EnglishSeries;
  onOpen: (series: EnglishSeries, episode: EnglishEpisode) => void;
}): JSX.Element {
  const [open, setOpen] = useState(true);
  const totalWords = series.episodes.reduce((sum, episode) => sum + (episode.card_count || episode.word_count), 0);

  return (
    <li className="ql-folder">
      <button type="button" className="ql-folder__head" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        <Folder size={20} className="ql-folder__icon" />
        <span className="ql-folder__name">{series.title}</span>
        <span className="ql-muted ql-folder__meta">
          {series.episodes.length} эп. · {totalWords} терминов
        </span>
      </button>
      {open && (
        <ul className="ql-set-grid">
          {series.episodes.map((episode) => (
            <li key={episode.id}>
              <button type="button" className="ql-card ql-set" onClick={() => onOpen(series, episode)}>
                <span className="ql-set__title">{episode.display_name}</span>
                {episode.title && <span className="ql-muted">{episode.title}</span>}
                <span className="ql-set__footer">
                  <span className="ql-chip">{episode.card_count || episode.word_count} терминов</span>
                  {episode.source === "ai_guess" && (
                    <span className="ql-badge ql-badge--warn">
                      <TriangleAlert size={12} /> неточно
                    </span>
                  )}
                  {episode.card_count === 0 && episode.word_count > 0 && (
                    <span className="ql-badge">карточки готовятся</span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function LibraryView({ library, error, onOpen, onImported }: LibraryViewProps): JSX.Element {
  const [credentialsOpen, setCredentialsOpen] = useState(false);

  return (
    <div className="ql-library">
      <div className="ql-row ql-row--spread">
        <h2 className="ql-page-title">Английский по сериалам</h2>
        <button type="button" className="ql-button ql-button--ghost" onClick={() => setCredentialsOpen(true)}>
          <KeyRound size={18} /> Источники субтитров
        </button>
      </div>
      <p className="ql-muted">
        Вставьте ссылку на серию — NABVE найдёт английские субтитры, выберет слова уровня A2–B1 и соберёт квиз.
      </p>

      <ImportPanel onImported={onImported} />

      {error && <p className="ql-error">{error}</p>}
      {library === null ? (
        <p className="ql-muted">Загрузка библиотеки…</p>
      ) : library.series.length === 0 ? (
        <div className="ql-card ql-empty">
          <p className="ql-empty__title">Пока пусто</p>
          <p className="ql-muted">Добавьте первую серию по ссылке или загрузите файл .srt.</p>
        </div>
      ) : (
        <ul className="ql-folders">
          {library.series.map((series) => (
            <SeriesFolder key={series.id} series={series} onOpen={onOpen} />
          ))}
        </ul>
      )}
      {library && <p className="ql-attribution">Уровни слов: {library.cefr_attribution}</p>}

      {credentialsOpen && <CredentialsDialog onClose={() => setCredentialsOpen(false)} />}
    </div>
  );
}
