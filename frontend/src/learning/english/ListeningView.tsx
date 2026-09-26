import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Check, Film, Headphones, RotateCcw, Volume2, X } from "lucide-react";
import { createListeningQuiz, getListeningClip, getListeningQuiz } from "../../api/english";
import type { ListeningQuiz } from "../../api/english";
import { playBase64 } from "./audio";

interface ListeningViewProps {
  episodeId: number;
  title: string;
  onExit: () => void;
}

type Phase = "loading" | "setup" | "generating" | "ready" | "quiz" | "done";

const KIND_LABELS: Record<string, string> = {
  who: "Кто сказал",
  meaning: "Смысл",
  next: "Что дальше",
};

export function ListeningView({ episodeId, title, onExit }: ListeningViewProps): JSX.Element {
  const [phase, setPhase] = useState<Phase>("loading");
  const [quiz, setQuiz] = useState<ListeningQuiz | null>(null);
  const [index, setIndex] = useState(0);
  const [chosen, setChosen] = useState<number | null>(null);
  const [missed, setMissed] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const canPickVideo = Boolean(window.assistantAPI?.pickVideoPath);

  useEffect(() => {
    getListeningQuiz(episodeId)
      .then((existing) => {
        setQuiz(existing);
        setPhase("ready");
      })
      .catch(() => setPhase("setup"));
  }, [episodeId]);

  const question = quiz?.questions[index];

  const play = useCallback(async (): Promise<void> => {
    if (!question) {
      return;
    }
    setPlaying(true);
    setError("");
    try {
      const clip = await getListeningClip(episodeId, question.cue_index);
      await playBase64(clip.audio_base64, clip.mime);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось воспроизвести реплику.");
    } finally {
      setPlaying(false);
    }
  }, [episodeId, question]);

  useEffect(() => {
    if (phase === "quiz") {
      void play();
    }
  }, [phase, index, play]);

  async function pickVideo(): Promise<void> {
    const path = await window.assistantAPI?.pickVideoPath?.();
    if (!path) {
      return;
    }
    setPhase("generating");
    setError("");
    try {
      setQuiz(await createListeningQuiz(episodeId, path));
      setPhase("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось составить квиз.");
      setPhase("setup");
    }
  }

  function start(): void {
    setIndex(0);
    setChosen(null);
    setMissed([]);
    setPhase("quiz");
  }

  function choose(option: number): void {
    if (!question || chosen !== null) {
      return;
    }
    setChosen(option);
    if (option !== question.correct_index) {
      setMissed((previous) => [...previous, index]);
    }
  }

  function next(): void {
    if (!quiz) {
      return;
    }
    if (index + 1 >= quiz.questions.length) {
      setPhase("done");
      return;
    }
    setIndex(index + 1);
    setChosen(null);
  }

  const header = (
    <div className="ql-learn__top">
      <button type="button" className="ql-icon-button" onClick={onExit} aria-label="Назад к эпизоду">
        <ArrowLeft size={20} />
      </button>
      <span className="ql-learn__title">Аудирование · {title}</span>
      {phase === "quiz" && quiz && (
        <span className="ql-muted">
          {index + 1} / {quiz.questions.length}
        </span>
      )}
    </div>
  );

  if (phase === "loading" || phase === "generating") {
    return (
      <div className="ql-learn">
        {header}
        <section className="ql-card ql-empty">
          <p className="ql-empty__title">{phase === "loading" ? "Загрузка…" : "Составляю вопросы по сериалу…"}</p>
          {phase === "generating" && <p className="ql-muted">Это может занять до минуты на локальной модели.</p>}
        </section>
      </div>
    );
  }

  if (phase === "setup" || phase === "ready") {
    return (
      <div className="ql-learn">
        {header}
        <section className="ql-card ql-listening-intro">
          <Headphones size={40} className="ql-listening-intro__icon" />
          <h2 className="ql-summary__title">Квиз на понимание на слух</h2>
          <p className="ql-muted">
            Реплики вырезаются прямо из вашего видеофайла серии: слушаете фразу и отвечаете, кто её сказал, что
            имелось в виду или что произошло дальше.
          </p>
          {phase === "ready" && quiz && (
            <p className="ql-chip">
              <Film size={14} /> {quiz.video_name} · {quiz.questions.length} вопросов
            </p>
          )}
          {error && <p className="ql-error">{error}</p>}
          <div className="ql-row">
            {phase === "ready" && (
              <button type="button" className="ql-button ql-button--primary ql-button--large" onClick={start}>
                <Headphones size={20} /> Начать
              </button>
            )}
            {canPickVideo ? (
              <button
                type="button"
                className={phase === "ready" ? "ql-button ql-button--ghost" : "ql-button ql-button--primary ql-button--large"}
                onClick={() => void pickVideo()}
              >
                <Film size={18} /> {phase === "ready" ? "Другое видео" : "Выбрать видеофайл серии"}
              </button>
            ) : (
              phase === "setup" && (
                <p className="ql-muted">Выбор видеофайла доступен только в приложении NABVE на компьютере.</p>
              )
            )}
          </div>
        </section>
      </div>
    );
  }

  if (phase === "done" && quiz) {
    const correct = quiz.questions.length - missed.length;
    return (
      <div className="ql-learn">
        {header}
        <section className="ql-card ql-summary">
          <h2 className="ql-summary__title">
            Правильно: {correct} из {quiz.questions.length}
          </h2>
          {missed.length > 0 ? (
            <>
              <h3 className="ql-section-title">Стоит переслушать</h3>
              <ul className="ql-term-list">
                {missed.map((missedIndex) => {
                  const item = quiz.questions[missedIndex];
                  return item ? (
                    <li key={item.cue_index} className="ql-term">
                      <span className="ql-term__word" lang="en">
                        {item.line}
                      </span>
                      <span className="ql-term__definition">
                        {item.question} — {item.options[item.correct_index]}
                      </span>
                      <span />
                    </li>
                  ) : null;
                })}
              </ul>
            </>
          ) : (
            <p className="ql-muted">Всё на слух — отлично!</p>
          )}
          <div className="ql-row">
            <button type="button" className="ql-button ql-button--primary" onClick={start}>
              <RotateCcw size={18} /> Ещё раз
            </button>
            <button type="button" className="ql-button ql-button--ghost" onClick={onExit}>
              К эпизоду
            </button>
          </div>
        </section>
      </div>
    );
  }

  const answered = chosen !== null;
  const progress = quiz ? Math.round(((index + (answered ? 1 : 0)) / quiz.questions.length) * 100) : 0;

  return (
    <div className="ql-learn">
      {header}
      <div className="ql-progress">
        <div className="ql-progress__fill" style={{ width: `${progress}%` }} />
      </div>
      {error && <p className="ql-error">{error}</p>}
      {question && (
        <section
          className={`ql-card ql-question${
            answered ? (chosen === question.correct_index ? " ql-question--good" : " ql-question--bad") : ""
          }`}
        >
          <div className="ql-question__meta">
            <span className="ql-chip">{KIND_LABELS[question.kind] ?? "Вопрос"}</span>
            <button type="button" className="ql-button ql-button--ghost" onClick={() => void play()} disabled={playing}>
              <Volume2 size={18} /> {playing ? "Играет…" : "Прослушать ещё раз"}
            </button>
          </div>
          <p className="ql-question__prompt">{question.question}</p>
          {answered && (
            <p className="ql-question__example" lang="en">
              «{question.line}»
            </p>
          )}
          <div className="ql-options__grid">
            {question.options.map((option, optionIndex) => {
              const state = !answered
                ? ""
                : optionIndex === question.correct_index
                  ? " ql-option--good"
                  : optionIndex === chosen
                    ? " ql-option--bad"
                    : " ql-option--dim";
              return (
                <button
                  key={option}
                  type="button"
                  className={`ql-option${state}`}
                  onClick={() => choose(optionIndex)}
                  disabled={answered}
                >
                  <span className="ql-option__key">
                    {answered && optionIndex === question.correct_index ? (
                      <Check size={14} />
                    ) : answered && optionIndex === chosen ? (
                      <X size={14} />
                    ) : (
                      optionIndex + 1
                    )}
                  </span>
                  <span>{option}</span>
                </button>
              );
            })}
          </div>
          {answered && (
            <button type="button" className="ql-button ql-button--primary" onClick={next}>
              {quiz && index + 1 >= quiz.questions.length ? "Итоги" : "Дальше"}
            </button>
          )}
        </section>
      )}
    </div>
  );
}
