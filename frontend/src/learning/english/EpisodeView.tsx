import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowLeft,
  Archive,
  GraduationCap,
  Headphones,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  deleteCard,
  getEpisodeCards,
  getJob,
  getLevelFilter,
  reanalyzeEpisode,
  startCardGeneration,
} from "../../api/english";
import type {
  CardJob,
  EnglishCard,
  EnglishEpisode,
  EnglishTitle,
  ItemKind,
  LearnSettings,
  LevelFilter,
  LevelFilterView,
} from "../../api/english";
import { FilterOverrideDialog } from "./FilterOverrideDialog";
import { LearnSettingsDialog } from "./LearnSettingsDialog";
import { formatTime } from "./format";
import { ITEM_KINDS, KIND_LABELS, applyFilter, filterSummary, isFilterEmpty, sensesByLemma } from "./levelFilter";

const JOB_POLL_MS = 2000;

interface EpisodeViewProps {
  title: EnglishTitle;
  episode: EnglishEpisode;
  initialJob: CardJob | null;
  settings: LearnSettings;
  headerActions?: ReactNode;
  onSettingsChange: (settings: LearnSettings) => void;
  onBack: () => void;
  onLearn: (cards: EnglishCard[], filter: LevelFilter) => void;
  onListening: () => void;
  onChanged: () => void;
  onVisibleCards?: (cards: EnglishCard[], filter: LevelFilter | null) => void;
}

type KindFilter = ItemKind | "all";

function LevelBadge({ card }: { card: EnglishCard }): JSX.Element {
  const label = card.cefr ?? "без уровня";
  return (
    <span className="ql-badge ql-badge--level" title={card.cefr_source === "ai" ? "Уровень оценён ИИ" : undefined}>
      {label}
      {card.cefr_source === "ai" ? " · ИИ" : ""}
    </span>
  );
}

function jobLabel(job: CardJob): string {
  return job.phase === "expressions"
    ? `Ищу идиомы и выражения: ${job.done} из ${job.total}`
    : `Создаю карточки: ${job.done} из ${job.total}`;
}

export function EpisodeView({
  title,
  episode,
  initialJob,
  settings,
  headerActions,
  onSettingsChange,
  onBack,
  onLearn,
  onListening,
  onChanged,
  onVisibleCards,
}: EpisodeViewProps): JSX.Element {
  const [cards, setCards] = useState<EnglishCard[] | null>(null);
  const [archived, setArchived] = useState<EnglishCard[]>([]);
  const [showArchive, setShowArchive] = useState(false);
  const [job, setJob] = useState<CardJob | null>(initialJob);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [filterView, setFilterView] = useState<LevelFilterView | null>(null);
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");

  const loadCards = useCallback(async (): Promise<void> => {
    try {
      const all = await getEpisodeCards(episode.id, true);
      setCards(all.filter((card) => !card.archived));
      setArchived(all.filter((card) => card.archived));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить карточки.");
    }
  }, [episode.id]);

  const loadFilter = useCallback(async (): Promise<void> => {
    try {
      setFilterView(await getLevelFilter("episode", episode.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить фильтр уровней.");
    }
  }, [episode.id]);

  useEffect(() => {
    void loadCards();
    void loadFilter();
  }, [loadCards, loadFilter]);

  useEffect(() => {
    if (!job || job.state !== "running") {
      return;
    }
    const timer = window.setTimeout(() => {
      getJob(job.id)
        .then((next) => {
          setJob(next);
          void loadCards();
          if (next.state !== "running") {
            onChanged();
          }
        })
        .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось узнать прогресс."));
    }, JOB_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [job, loadCards, onChanged]);

  const filter = useMemo<LevelFilter | null>(
    () =>
      filterView
        ? { levels: filterView.levels, include_unleveled: filterView.include_unleveled, mwe_mode: filterView.mwe_mode }
        : null,
    [filterView],
  );
  const leveled = useMemo(() => (cards && filter ? applyFilter(cards, filter) : []), [cards, filter]);
  const visible = useMemo(
    () => (kindFilter === "all" ? leveled : leveled.filter((card) => card.kind === kindFilter)),
    [kindFilter, leveled],
  );
  const senses = useMemo(() => sensesByLemma(cards ?? []), [cards]);
  const presentKinds = useMemo(
    () => ITEM_KINDS.filter((kind) => leveled.some((card) => card.kind === kind)),
    [leveled],
  );

  useEffect(() => {
    onVisibleCards?.(leveled, filter);
  }, [leveled, filter, onVisibleCards]);

  async function generate(): Promise<void> {
    setError("");
    try {
      setJob(await startCardGeneration(episode.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось запустить генерацию.");
    }
  }

  async function reanalyze(): Promise<void> {
    setError("");
    setNotice("");
    try {
      const result = await reanalyzeEpisode(episode.id);
      setNotice(`Переанализировано: ${result.candidates} кандидатов, в архив ${result.archived}, вернулось ${result.restored}.`);
      if (result.job) {
        setJob(result.job);
      }
      await loadCards();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось переанализировать.");
    }
  }

  async function remove(card: EnglishCard): Promise<void> {
    try {
      await deleteCard(card.id);
      setCards((previous) => previous?.filter((item) => item.id !== card.id) ?? null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить карточку.");
    }
  }

  const running = job?.state === "running";
  const pendingWords = Math.max(0, episode.word_count - (cards?.length ?? 0) - archived.length);
  const jobPercent = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
  const empty = filter !== null && isFilterEmpty(filter);
  const heading = episode.season !== null ? `${episode.code}${episode.title ? ` — ${episode.title}` : ""}` : episode.code;

  return (
    <div className="ql-episode">
      <div className="ql-learn__top">
        <button type="button" className="ql-icon-button" onClick={onBack} aria-label="Назад к библиотеке">
          <ArrowLeft size={20} />
        </button>
        <div className="ql-episode__heading">
          <span className="ql-muted">{title.display_name}</span>
          <h2 className="ql-episode__title">{heading}</h2>
        </div>
        <div className="ql-top-actions">
          <button
            type="button"
            className={filterView?.source === "episode" ? "ql-icon-button ql-icon-button--marked" : "ql-icon-button"}
            onClick={() => setOverrideOpen(true)}
            aria-label="Свои настройки уровней для эпизода"
            title="Свои настройки уровней"
          >
            <SlidersHorizontal size={20} />
          </button>
          {headerActions}
        </div>
      </div>

      {episode.source === "ai_guess" && (
        <p className="ql-banner ql-banner--warn">
          <TriangleAlert size={18} /> Неточно: субтитры не нашлись, слова подобраны ИИ по знаниям о серии. Примеры
          могут не совпадать с реальными репликами.
        </p>
      )}

      {filter && (
        <p className="ql-active-levels">
          Уровни: {filterSummary(filter)}
          {filterView && filterView.source !== "global" && (
            <span className="ql-badge">{filterView.source === "episode" ? "свои для эпизода" : "свои для тайтла"}</span>
          )}
        </p>
      )}

      <div className="ql-row ql-row--spread">
        <button
          type="button"
          className="ql-button ql-button--primary ql-button--large"
          onClick={() => filter && onLearn(leveled, filter)}
          disabled={empty || leveled.length === 0}
        >
          <GraduationCap size={20} /> Заучивание
        </button>
        <div className="ql-row">
          {episode.source !== "ai_guess" && (
            <button type="button" className="ql-button ql-button--ghost" onClick={onListening}>
              <Headphones size={18} /> Аудирование
            </button>
          )}
          <button type="button" className="ql-button ql-button--ghost" onClick={() => void reanalyze()} disabled={running}>
            <RefreshCw size={18} /> Переанализировать
          </button>
          <button type="button" className="ql-button ql-button--ghost" onClick={() => setSettingsOpen(true)}>
            <Settings2 size={18} /> Настройки
          </button>
        </div>
      </div>

      {running && job && (
        <div className="ql-card ql-job">
          <span>{jobLabel(job)}</span>
          <div className="ql-progress">
            <div className="ql-progress__fill" style={{ width: `${jobPercent}%` }} />
          </div>
        </div>
      )}
      {job?.state === "failed" && <p className="ql-error">Генерация остановилась: {job.error}</p>}
      {!running && pendingWords > 0 && cards !== null && (
        <button type="button" className="ql-button ql-button--ghost" onClick={() => void generate()}>
          <Sparkles size={18} /> Создать карточки для оставшихся слов ({pendingWords})
        </button>
      )}
      {error && <p className="ql-error">{error}</p>}
      {notice && <p className="ql-muted">{notice}</p>}

      <div className="ql-row ql-row--spread">
        <h3 className="ql-section-title">Термины ({visible.length})</h3>
        {presentKinds.length > 1 && (
          <div className="ql-kind-filter" role="group" aria-label="Фильтр по типу">
            {(["all", ...presentKinds] as KindFilter[]).map((kind) => (
              <button
                key={kind}
                type="button"
                className={kindFilter === kind ? "ql-chip ql-chip--active" : "ql-chip"}
                aria-pressed={kindFilter === kind}
                onClick={() => setKindFilter(kind)}
              >
                {kind === "all" ? "все" : KIND_LABELS[kind]}
              </button>
            ))}
          </div>
        )}
      </div>

      {cards === null || filter === null ? (
        <p className="ql-muted">Загрузка…</p>
      ) : empty ? (
        <div className="ql-card ql-empty">
          <p className="ql-empty__title">Не выбран ни один уровень</p>
          <p className="ql-muted">Отметьте хотя бы один уровень в настройках модуля или «своих настройках» эпизода.</p>
        </div>
      ) : visible.length === 0 ? (
        <p className="ql-muted">
          {running ? "Карточки появятся здесь по мере готовности." : "Под выбранные уровни карточек нет."}
        </p>
      ) : (
        <ul className="ql-term-list">
          {visible.map((card) => (
            <li key={card.id} className="ql-term">
              <div className="ql-term__word">
                <span lang="en">
                  {card.word}
                  {card.sense_label && (senses.get(card.lemma) ?? 0) > 1 && (
                    <span className="ql-term__sense"> — {card.sense_label}</span>
                  )}
                </span>
                <span className="ql-term__badges">
                  <span className={`ql-badge ql-badge--kind ql-badge--${card.kind}`}>{KIND_LABELS[card.kind]}</span>
                  <LevelBadge card={card} />
                  <span className="ql-term__meta">{formatTime(card.timestamp_ms)}</span>
                </span>
              </div>
              <div className="ql-term__definition">
                <span>{card.translations_ru.join(", ")}</span>
                {card.literal_translation && <span className="ql-muted">дословно: {card.literal_translation}</span>}
                <span className="ql-term__example" lang="en">
                  {card.example}
                </span>
              </div>
              <button
                type="button"
                className="ql-icon-button ql-term__delete"
                onClick={() => void remove(card)}
                aria-label={`Удалить «${card.word}»`}
                title="Удалить карточку"
              >
                <Trash2 size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {archived.length > 0 && (
        <div className="ql-archive">
          <button type="button" className="ql-button ql-button--ghost" onClick={() => setShowArchive(!showArchive)}>
            <Archive size={16} /> Архив ({archived.length}) — слова, вошедшие в выражения
          </button>
          {showArchive && (
            <ul className="ql-term-list ql-term-list--archived">
              {archived.map((card) => (
                <li key={card.id} className="ql-term">
                  <span className="ql-term__word" lang="en">
                    {card.word}
                  </span>
                  <span className="ql-term__definition">{card.translations_ru.join(", ")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {settingsOpen && (
        <LearnSettingsDialog
          settings={settings}
          onClose={() => setSettingsOpen(false)}
          onSave={(next) => {
            onSettingsChange(next);
            setSettingsOpen(false);
          }}
        />
      )}
      {overrideOpen && (
        <FilterOverrideDialog
          scope="episode"
          scopeId={episode.id}
          label={episode.code}
          onClose={() => setOverrideOpen(false)}
          onChanged={(view) => {
            setFilterView(null);
            void loadFilter();
            onChanged();
            if (view.source !== "episode") {
              setKindFilter("all");
            }
          }}
        />
      )}
    </div>
  );
}
