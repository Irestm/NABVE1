import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, GraduationCap, Headphones, Settings2, Sparkles, Trash2, TriangleAlert } from "lucide-react";
import { deleteCard, getEpisodeCards, getJob, startCardGeneration } from "../../api/english";
import type { CardJob, EnglishCard, EnglishEpisode, LearnSettings } from "../../api/english";
import { LearnSettingsDialog } from "./LearnSettingsDialog";

const JOB_POLL_MS = 2000;

interface EpisodeViewProps {
  seriesTitle: string;
  episode: EnglishEpisode;
  initialJob: CardJob | null;
  settings: LearnSettings;
  onSettingsChange: (settings: LearnSettings) => void;
  onBack: () => void;
  onLearn: (cards: EnglishCard[]) => void;
  onListening: () => void;
  onChanged: () => void;
}

function formatTime(ms: number): string {
  const total = Math.floor(ms / 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const pad = (value: number): string => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${minutes}:${pad(seconds)}`;
}

export function EpisodeView({
  seriesTitle,
  episode,
  initialJob,
  settings,
  onSettingsChange,
  onBack,
  onLearn,
  onListening,
  onChanged,
}: EpisodeViewProps): JSX.Element {
  const [cards, setCards] = useState<EnglishCard[] | null>(null);
  const [job, setJob] = useState<CardJob | null>(initialJob);
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const loadCards = useCallback(async (): Promise<void> => {
    try {
      setCards(await getEpisodeCards(episode.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить карточки.");
    }
  }, [episode.id]);

  useEffect(() => {
    void loadCards();
  }, [loadCards]);

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

  async function generate(): Promise<void> {
    setError("");
    try {
      setJob(await startCardGeneration(episode.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось запустить генерацию.");
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
  const pendingWords = Math.max(0, episode.word_count - (cards?.length ?? 0));
  const jobPercent = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;

  return (
    <div className="ql-episode">
      <div className="ql-learn__top">
        <button type="button" className="ql-icon-button" onClick={onBack} aria-label="Назад к библиотеке">
          <ArrowLeft size={20} />
        </button>
        <div className="ql-episode__heading">
          <span className="ql-muted">{seriesTitle}</span>
          <h2 className="ql-episode__title">
            {episode.code}
            {episode.title ? ` — ${episode.title}` : ""}
          </h2>
        </div>
      </div>

      {episode.source === "ai_guess" && (
        <p className="ql-banner ql-banner--warn">
          <TriangleAlert size={18} /> Неточно: субтитры не нашлись, слова подобраны ИИ по знаниям о серии. Примеры
          могут не совпадать с реальными репликами.
        </p>
      )}

      <div className="ql-row ql-row--spread">
        <button
          type="button"
          className="ql-button ql-button--primary ql-button--large"
          onClick={() => cards && onLearn(cards)}
          disabled={!cards || cards.length === 0}
        >
          <GraduationCap size={20} /> Заучивание
        </button>
        <div className="ql-row">
          {episode.source !== "ai_guess" && (
            <button type="button" className="ql-button ql-button--ghost" onClick={onListening}>
              <Headphones size={18} /> Аудирование
            </button>
          )}
          <button type="button" className="ql-button ql-button--ghost" onClick={() => setSettingsOpen(true)}>
            <Settings2 size={18} /> Настройки
          </button>
        </div>
      </div>

      {running && job && (
        <div className="ql-card ql-job">
          <span>
            Создаю карточки: {job.done} из {job.total}
          </span>
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

      <h3 className="ql-section-title">Термины в этом эпизоде ({cards?.length ?? 0})</h3>
      {cards === null ? (
        <p className="ql-muted">Загрузка…</p>
      ) : cards.length === 0 ? (
        <p className="ql-muted">{running ? "Карточки появятся здесь по мере готовности." : "Карточек пока нет."}</p>
      ) : (
        <ul className="ql-term-list">
          {cards.map((card) => (
            <li key={card.id} className="ql-term">
              <div className="ql-term__word">
                <span lang="en">{card.word}</span>
                <span className="ql-term__meta">
                  {card.cefr ?? "сленг"} · {formatTime(card.timestamp_ms)}
                </span>
              </div>
              <div className="ql-term__definition">
                <span>{card.translations_ru.join(", ")}</span>
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
    </div>
  );
}
