import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ArrowLeft, Check, Mic, RotateCcw, Volume2, X } from "lucide-react";
import { finishSession, sendAnswer, startSession } from "../../api/english";
import type { AnswerResult, EnglishCard, LearnSettings, LevelFilter, SessionSummary } from "../../api/english";
import { answerText, applyAnswer, buildOptions, contextLine, initialState, promptText, showsContext } from "./learnQueue";
import { KIND_LABELS, filterSummary, sensesByLemma } from "./levelFilter";
import type { LearnState } from "./learnQueue";
import { useOneShotVoiceInput } from "../../hooks/useOneShotVoiceInput";
import { speakEnglish } from "./audio";

export interface LearnProgress {
  card: EnglishCard | null;
  answered: boolean;
  mistakes: { card: EnglishCard; given: string }[];
}

interface LearnViewProps {
  episodeId: number;
  title: string;
  cards: EnglishCard[];
  settings: LearnSettings;
  filter: LevelFilter;
  headerActions?: ReactNode;
  onExit: () => void;
  onProgress?: (progress: LearnProgress) => void;
}

interface Feedback {
  given: string;
  result: AnswerResult;
}

export function LearnView({
  episodeId,
  title,
  cards,
  settings,
  filter,
  headerActions,
  onExit,
  onProgress,
}: LearnViewProps): JSX.Element {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [state, setState] = useState<LearnState>(() => initialState(cards, settings));
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<SessionSummary | null>(null);
  const [mistakes, setMistakes] = useState<{ card: EnglishCard; given: string }[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const continueRef = useRef<HTMLButtonElement>(null);

  const cardsById = useMemo(() => new Map(cards.map((card) => [card.id, card])), [cards]);
  const senses = useMemo(() => sensesByLemma(cards), [cards]);
  const current = state.queue[0];
  const card = current ? cardsById.get(current.cardId) : undefined;
  const options = useMemo(
    () => (card && current?.stage === "choice" ? buildOptions(card, cards, settings.direction) : []),
    [card, cards, current?.stage, settings.direction, state.points, state.queue.length],
  );

  useEffect(() => {
    let cancelled = false;
    startSession(episodeId, settings)
      .then((session) => {
        if (!cancelled) {
          setSessionId(session.id);
        }
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось начать заучивание."));
    return () => {
      cancelled = true;
    };
  }, [episodeId, settings]);

  useEffect(() => {
    if (sessionId === null || summary || state.queue.length > 0) {
      return;
    }
    finishSession(sessionId)
      .then(setSummary)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Не удалось подвести итоги."));
  }, [sessionId, state.queue.length, summary]);

  useEffect(() => {
    if (feedback) {
      continueRef.current?.focus();
    } else if (current?.stage === "input") {
      inputRef.current?.focus();
    }
  }, [feedback, current]);

  const submit = useCallback(
    async (given: string): Promise<void> => {
      if (!card || !current || sessionId === null || busy || feedback) {
        return;
      }
      setBusy(true);
      setError("");
      try {
        const result = await sendAnswer(sessionId, card.id, current.stage, given);
        setFeedback({ given, result });
        if (!result.correct) {
          setMistakes((previous) => [...previous, { card, given }]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось проверить ответ.");
      } finally {
        setBusy(false);
      }
    },
    [busy, card, current, feedback, sessionId],
  );

  const proceed = useCallback((): void => {
    if (!feedback) {
      return;
    }
    setState((previous) => applyAnswer(previous, feedback.result.correct, settings.mode));
    setFeedback(null);
    setTyped("");
  }, [feedback, settings.mode]);

  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (feedback && event.key === "Enter") {
        event.preventDefault();
        proceed();
        return;
      }
      if (!feedback && current?.stage === "choice" && /^[1-4]$/.test(event.key)) {
        const option = options[Number(event.key) - 1];
        if (option !== undefined) {
          void submit(option);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current?.stage, feedback, options, proceed, submit]);

  const voice = useOneShotVoiceInput(
    (text) => {
      setTyped(text);
      void submit(text);
    },
    settings.direction === "en_ru" ? "ru" : "en",
  );

  function sayWord(target: EnglishCard): void {
    speakEnglish(target.word).catch((err: unknown) =>
      setError(err instanceof Error ? err.message : "Не удалось озвучить слово."),
    );
  }

  useEffect(() => {
    onProgress?.({ card: card ?? null, answered: feedback !== null, mistakes });
  }, [card, feedback, mistakes, onProgress]);

  const progress = state.totalPoints === 0 ? 0 : Math.round((state.points / state.totalPoints) * 100);

  if (summary) {
    return (
      <div className="ql-learn">
        <div className="ql-learn__top">
          <button type="button" className="ql-icon-button" onClick={onExit} aria-label="Назад к эпизоду">
            <ArrowLeft size={20} />
          </button>
          <span className="ql-learn__title">{title}</span>
          {headerActions}
        </div>
        <section className="ql-card ql-summary">
          <h2 className="ql-summary__title">Готово! Выучено карточек: {cards.length}</h2>
          <p className="ql-summary__stat">
            Ошибок: <strong>{summary.mistakes}</strong>
          </p>
          {summary.hard_words.length > 0 ? (
            <>
              <h3 className="ql-section-title">Сложные слова</h3>
              <ul className="ql-term-list">
                {summary.hard_words.map(({ card: hard, mistakes }) => (
                  <li key={hard.id} className="ql-term">
                    <span className="ql-term__word">{hard.word}</span>
                    <span className="ql-term__definition">{hard.translations_ru.join(", ")}</span>
                    <span className="ql-badge ql-badge--bad">×{mistakes}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="ql-muted">Без единой ошибки — отлично!</p>
          )}
          <div className="ql-row">
            <button type="button" className="ql-button ql-button--primary" onClick={onExit}>
              <RotateCcw size={18} /> К эпизоду
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="ql-learn">
      <div className="ql-learn__top">
        <button type="button" className="ql-icon-button" onClick={onExit} aria-label="Выйти из заучивания">
          <X size={20} />
        </button>
        <span className="ql-learn__title">{title}</span>
        <span className="ql-muted">
          {state.learned.length} / {cards.length}
        </span>
        {headerActions}
      </div>
      <p className="ql-active-levels">Уровни: {filterSummary(filter)}</p>
      <div className="ql-progress" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
        <div className="ql-progress__fill" style={{ width: `${progress}%` }} />
      </div>

      {(error || voice.error) && <p className="ql-error">{error || voice.error}</p>}

      {card && current && (
        <section
          className={`ql-card ql-question${feedback ? (feedback.result.correct ? " ql-question--good" : " ql-question--bad") : ""}`}
        >
          <div className="ql-question__meta">
            <span className="ql-muted">{settings.direction === "en_ru" ? "Термин" : "Определение"}</span>
            {card.kind !== "word" && <span className={`ql-badge ql-badge--kind ql-badge--${card.kind}`}>{KIND_LABELS[card.kind]}</span>}
            {current.stage === "input" && <span className="ql-chip">Напишите ответ</span>}
          </div>
          <div className="ql-prompt-row">
            <p className="ql-question__prompt" lang={settings.direction === "en_ru" ? "en" : "ru"}>
              {promptText(card, settings.direction)}
            </p>
            {(settings.direction === "en_ru" || feedback) && (
              <button
                type="button"
                className="ql-icon-button ql-voice-button"
                onClick={() => sayWord(card)}
                aria-label={`Произнести «${card.word}»`}
                title="Произнести по-английски"
              >
                <Volume2 size={20} />
              </button>
            )}
          </div>
          {(showsContext(card, settings) || (senses.get(card.lemma) ?? 0) > 1 || feedback !== null) && (
            <p className="ql-question__example" lang="en">
              «{feedback ? card.example : contextLine(card, settings.direction)}»
            </p>
          )}

          {feedback ? (
            <div className="ql-feedback">
              {feedback.result.correct ? (
                <p className="ql-feedback__title ql-feedback__title--good">
                  <Check size={20} /> {feedback.result.exact ? "Отлично!" : "Засчитано — есть опечатка"}
                </p>
              ) : (
                <p className="ql-feedback__title ql-feedback__title--bad">
                  <X size={20} /> Не совсем — повторим позже
                </p>
              )}
              {!feedback.result.correct && feedback.given && (
                <p className="ql-answer ql-answer--bad">Ваш ответ: {feedback.given}</p>
              )}
              <p className="ql-answer ql-answer--good">
                Правильный ответ: {feedback.result.expected.join(" / ") || answerText(card, settings.direction)}
              </p>
              {card.kind === "idiom" && card.literal_translation && (
                <p className="ql-muted">дословно: {card.literal_translation}</p>
              )}
              <button ref={continueRef} type="button" className="ql-button ql-button--primary" onClick={proceed}>
                Продолжить
              </button>
            </div>
          ) : current.stage === "choice" ? (
            <div className="ql-options">
              <span className="ql-muted">Выберите правильный ответ</span>
              <div className="ql-options__grid">
                {options.map((option, index) => (
                  <button
                    key={option}
                    type="button"
                    className="ql-option"
                    onClick={() => void submit(option)}
                    disabled={busy || sessionId === null}
                  >
                    <span className="ql-option__key">{index + 1}</span>
                    <span>{option}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <form
              className="ql-input-row"
              onSubmit={(event) => {
                event.preventDefault();
                void submit(typed);
              }}
            >
              <input
                ref={inputRef}
                className="ql-input"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder={settings.direction === "en_ru" ? "Перевод на русском" : "Слово на английском"}
                lang={settings.direction === "en_ru" ? "ru" : "en"}
                autoComplete="off"
                spellCheck={false}
                disabled={busy || sessionId === null}
              />
              <button
                type="button"
                className={`ql-icon-button ql-voice-button${voice.recording ? " ql-voice-button--recording" : ""}`}
                onClick={voice.start}
                disabled={busy || voice.recording || sessionId === null}
                aria-label="Ответить голосом"
                title="Ответить голосом"
              >
                <Mic size={20} />
              </button>
              <button type="button" className="ql-button ql-button--ghost" onClick={() => void submit("")} disabled={busy}>
                Не знаю
              </button>
              <button type="submit" className="ql-button ql-button--primary" disabled={busy || !typed.trim()}>
                Ответить
              </button>
            </form>
          )}
        </section>
      )}
    </div>
  );
}
