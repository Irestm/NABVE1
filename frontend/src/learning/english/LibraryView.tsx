import { useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, ChevronRight, Clapperboard, Folder, KeyRound, Settings2, SlidersHorizontal, TriangleAlert } from "lucide-react";
import type { EnglishEpisode, EnglishLibrary, EnglishTitle, ImportedEpisode } from "../../api/english";
import { CredentialsDialog } from "./CredentialsDialog";
import { FilterOverrideDialog } from "./FilterOverrideDialog";
import { ImportPanel } from "./ImportPanel";
import { phrasesLabel, pluralRu, wordsLabel } from "./format";

interface LibraryViewProps {
  library: EnglishLibrary | null;
  error: string;
  headerActions?: ReactNode;
  onOpen: (title: EnglishTitle, episode: EnglishEpisode) => void;
  onImported: (imported: ImportedEpisode) => void;
  onOpenSettings: () => void;
  onFiltersChanged: () => void;
}

function EpisodeTile({
  title,
  episode,
  onOpen,
}: {
  title: EnglishTitle;
  episode: EnglishEpisode;
  onOpen: (title: EnglishTitle, episode: EnglishEpisode) => void;
}): JSX.Element {
  const hasCards = episode.card_count > 0;
  return (
    <li>
      <button type="button" className="ql-card ql-set" onClick={() => onOpen(title, episode)}>
        <span className="ql-set__title">{episode.display_name}</span>
        {episode.title && <span className="ql-muted">{episode.title}</span>}
        <span className="ql-set__footer">
          <span className="ql-chip">{wordsLabel(episode.words)}</span>
          <span className="ql-chip">{phrasesLabel(episode.phrases)}</span>
          {episode.source === "ai_guess" && (
            <span className="ql-badge ql-badge--warn">
              <TriangleAlert size={12} /> неточно
            </span>
          )}
          {!hasCards && episode.word_count > 0 && <span className="ql-badge">карточки не созданы</span>}
          {episode.has_override && <span className="ql-badge">свои уровни</span>}
        </span>
      </button>
    </li>
  );
}

function TitleFolder({
  title,
  onOpen,
  onOverride,
}: {
  title: EnglishTitle;
  onOpen: (title: EnglishTitle, episode: EnglishEpisode) => void;
  onOverride: (title: EnglishTitle) => void;
}): JSX.Element {
  const [open, setOpen] = useState(true);
  const Icon = title.kind === "movie" ? Clapperboard : Folder;
  const meta =
    title.kind === "movie"
      ? title.episodes.length > 1
        ? pluralRu(title.episodes.length, "часть", "части", "частей")
        : "целиком"
      : `${title.episodes.length} эп. · ${wordsLabel(title.words)}, ${phrasesLabel(title.phrases)}`;

  return (
    <li className="ql-folder">
      <div className="ql-folder__row">
        <button type="button" className="ql-folder__head" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          <Icon size={20} className="ql-folder__icon" />
          <span className="ql-folder__name">{title.display_name}</span>
          <span className="ql-muted ql-folder__meta">{meta}</span>
        </button>
        <button
          type="button"
          className={title.has_override ? "ql-icon-button ql-icon-button--marked" : "ql-icon-button"}
          onClick={() => onOverride(title)}
          aria-label={`Свои настройки уровней для «${title.name}»`}
          title="Свои настройки уровней"
        >
          <SlidersHorizontal size={18} />
        </button>
      </div>
      {open && (
        <ul className="ql-set-grid">
          {title.episodes.map((episode) => (
            <EpisodeTile key={episode.id} title={title} episode={episode} onOpen={onOpen} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function LibraryView({
  library,
  error,
  headerActions,
  onOpen,
  onImported,
  onOpenSettings,
  onFiltersChanged,
}: LibraryViewProps): JSX.Element {
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [override, setOverride] = useState<EnglishTitle | null>(null);

  return (
    <div className="ql-library">
      <div className="ql-row ql-row--spread">
        <h2 className="ql-page-title">Английский по сериалам и фильмам</h2>
        <div className="ql-row">
          <button type="button" className="ql-button ql-button--ghost" onClick={() => setCredentialsOpen(true)}>
            <KeyRound size={18} /> Источники субтитров
          </button>
          <button
            type="button"
            className="ql-icon-button"
            onClick={onOpenSettings}
            aria-label="Настройки английского"
            title="Настройки английского"
          >
            <Settings2 size={20} />
          </button>
          {headerActions}
        </div>
      </div>
      <p className="ql-muted">
        Вставьте ссылку на серию или фильм — NABVE найдёт английские субтитры, выберет слова и выражения и соберёт квиз.
      </p>

      <ImportPanel onImported={onImported} />

      {error && <p className="ql-error">{error}</p>}
      {library === null ? (
        <p className="ql-muted">Загрузка библиотеки…</p>
      ) : library.titles.length === 0 ? (
        <div className="ql-card ql-empty">
          <p className="ql-empty__title">Пока пусто</p>
          <p className="ql-muted">Добавьте первую серию или фильм по ссылке или загрузите файл .srt.</p>
        </div>
      ) : (
        <ul className="ql-folders">
          {library.titles.map((title) => (
            <TitleFolder key={title.id} title={title} onOpen={onOpen} onOverride={setOverride} />
          ))}
        </ul>
      )}
      {library && (
        <p className="ql-attribution">
          Уровни слов: {library.cefr_attribution}. Выражения: {library.lexicon_attribution}.
        </p>
      )}

      {credentialsOpen && <CredentialsDialog onClose={() => setCredentialsOpen(false)} />}
      {override && (
        <FilterOverrideDialog
          scope="title"
          scopeId={override.id}
          label={override.display_name}
          onClose={() => setOverride(null)}
          onChanged={onFiltersChanged}
        />
      )}
    </div>
  );
}
