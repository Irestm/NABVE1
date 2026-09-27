import { useState } from "react";
import { BookOpenCheck, Download, ListTree, Microscope, Sparkles } from "lucide-react";
import { analyzeTitle, generateTitleCards, wordsAboveLevel } from "../../api/english";
import type { AboveLevelWord, AnalysisOffer, DifficultyResult } from "../../api/english";
import type { AssistantActions, ChatMessage } from "../../components/assistant/types";

const LEVEL_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2", "none"] as const;
const LEVEL_COLORS: Record<(typeof LEVEL_ORDER)[number], string> = {
  A1: "#4a58d6",
  A2: "#6474ee",
  B1: "#8290ff",
  B2: "#a2acff",
  C1: "#c2c8ff",
  C2: "#dfe2ff",
  none: "#6b7280",
};
const VERDICT_CLASS: Record<DifficultyResult["verdict"], string> = {
  Подходит: "ql-verdict--good",
  "Подходит с усилием": "ql-verdict--warn",
  "Пока рано": "ql-verdict--bad",
};

function levelLabel(level: string): string {
  return level === "none" ? "без уровня" : level;
}

function Distribution({ distribution }: { distribution: Record<string, number> }): JSX.Element {
  const total = LEVEL_ORDER.reduce((sum, level) => sum + (distribution[level] ?? 0), 0) || 1;
  return (
    <figure className="ql-dist">
      <figcaption className="ql-dist__caption">Слова по уровням</figcaption>
      <div className="ql-dist__bar" role="img" aria-label="Распределение слов по уровням CEFR">
        {LEVEL_ORDER.map((level) => {
          const value = distribution[level] ?? 0;
          if (!value) {
            return null;
          }
          const share = (value / total) * 100;
          return (
            <span
              key={level}
              className="ql-dist__segment"
              style={{ width: `${share}%`, background: LEVEL_COLORS[level] }}
              title={`${levelLabel(level)}: ${share.toFixed(1)}% (${value})`}
            />
          );
        })}
      </div>
      <ul className="ql-dist__legend">
        {LEVEL_ORDER.map((level) => (
          <li key={level}>
            <span className="ql-dist__swatch" style={{ background: LEVEL_COLORS[level] }} aria-hidden="true" />
            {levelLabel(level)} {(((distribution[level] ?? 0) / total) * 100).toFixed(0)}%
          </li>
        ))}
      </ul>
    </figure>
  );
}

export function DifficultyCard({ result }: { result: DifficultyResult }): JSX.Element {
  const [words, setWords] = useState<AboveLevelWord[] | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const percent = Math.round(result.coverage * 1000) / 10;

  async function showWords(): Promise<void> {
    if (result.title_id === null) {
      return;
    }
    setBusy(true);
    try {
      setWords(await wordsAboveLevel(result.title_id));
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Не удалось загрузить слова.");
    } finally {
      setBusy(false);
    }
  }

  async function importCards(): Promise<void> {
    if (result.title_id === null) {
      return;
    }
    setBusy(true);
    try {
      const started = await generateTitleCards(result.title_id);
      setNotice(`Запустил создание карточек: ${started.jobs} эп./част. Они появятся в библиотеке.`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Не удалось запустить импорт.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ql-difficulty">
      <div className="ql-difficulty__head">
        <span className={`ql-verdict ${VERDICT_CLASS[result.verdict]}`}>{result.verdict}</span>
        <span className="ql-muted">
          {result.title}
          {result.year ? ` (${result.year})` : ""} · уровень {result.user_level}
        </span>
      </div>
      <div className="ql-coverage">
        <div className="ql-coverage__label">
          <span>Покрытие известными словами</span>
          <strong>{percent.toFixed(1)}%</strong>
        </div>
        <div
          className="ql-coverage__track"
          role="meter"
          aria-valuemin={80}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-label="Покрытие"
        >
          <span className="ql-coverage__fill" style={{ width: `${Math.max(0, Math.min(100, (percent - 80) * 5))}%` }} />
          <span className="ql-coverage__mark" style={{ left: "75%" }} title="95% — смотрится с усилием" />
          <span className="ql-coverage__mark" style={{ left: "90%" }} title="98% — комфортно" />
        </div>
        <div className="ql-coverage__scale" aria-hidden="true">
          <span style={{ left: "0%" }}>80%</span>
          <span style={{ left: "75%" }}>95%</span>
          <span style={{ left: "90%" }}>98%</span>
        </div>
      </div>
      <Distribution distribution={result.distribution} />
      <p className="ql-muted">
        Темп {Math.round(result.words_per_minute)} слов/мин · выше уровня: {result.above_level_count} · по субтитрам{" "}
        {result.episodes_analyzed} {result.kind === "movie" ? "част." : "эп."}
      </p>
      {result.examples.length > 0 && (
        <div className="ql-difficulty__examples">
          {result.examples.map((word) => (
            <span key={word} className="ql-chip" lang="en">
              {word}
            </span>
          ))}
        </div>
      )}
      <div className="ql-row">
        {!result.has_cards && result.title_id !== null && (
          <button type="button" className="ql-button ql-button--ghost ql-button--small" onClick={() => void importCards()} disabled={busy}>
            <Download size={15} /> Импортировать
          </button>
        )}
        {result.title_id !== null && (
          <button type="button" className="ql-button ql-button--ghost ql-button--small" onClick={() => void showWords()} disabled={busy}>
            <ListTree size={15} /> Показать все слова выше моего уровня
          </button>
        )}
      </div>
      {notice && <p className="ql-muted">{notice}</p>}
      {words && (
        <ul className="ql-above-list">
          {words.length === 0 ? (
            <li className="ql-muted">Таких слов нет.</li>
          ) : (
            words.map((word) => (
              <li key={word.lemma}>
                <span lang="en">{word.lemma}</span>
                <span className="ql-muted">
                  {word.level} · ×{word.count}
                </span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

export function OfferCard({ offer, actions }: { offer: AnalysisOffer; actions: AssistantActions }): JSX.Element {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const name = `${offer.title}${offer.year ? ` (${offer.year})` : ""}`;

  async function analyze(): Promise<void> {
    setBusy(true);
    setNotice("Скачиваю субтитры и считаю статистику…");
    try {
      const result = await analyzeTitle(offer);
      if (result.status === "analyzed" && result.title_id !== null) {
        setNotice("");
        actions.send(`Проанализируй «${name}»`, {
          action: { type: "difficulty_check", title: offer.title, year: offer.year, kind: offer.kind, title_id: result.title_id },
        });
      } else {
        const options = result.options.length ? ` Варианты: ${result.options.join("; ")}.` : "";
        setNotice(`${result.message}${options}`);
      }
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Не удалось проанализировать.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ql-offer">
      <div className="ql-row">
        <button type="button" className="ql-button ql-button--primary ql-button--small" onClick={() => void analyze()} disabled={busy || actions.busy}>
          <Microscope size={15} /> Проанализировать
        </button>
        <button
          type="button"
          className="ql-button ql-button--ghost ql-button--small"
          onClick={() =>
            actions.send(`Оцени «${name}» по общим знаниям`, {
              action: { type: "difficulty_general", title: offer.title, year: offer.year, kind: offer.kind },
            })
          }
          disabled={busy || actions.busy}
        >
          <Sparkles size={15} /> Без анализа
        </button>
      </div>
      {notice && <p className="ql-muted">{notice}</p>}
    </div>
  );
}

export function renderEnglishMeta(message: ChatMessage, actions: AssistantActions): JSX.Element | null {
  const meta = message.meta ?? {};
  if (meta.difficulty) {
    return <DifficultyCard result={meta.difficulty as DifficultyResult} />;
  }
  if (meta.offer) {
    return <OfferCard offer={meta.offer as AnalysisOffer} actions={actions} />;
  }
  if (meta.source === "general_knowledge") {
    return (
      <span className="ql-badge ql-badge--warn">
        <BookOpenCheck size={12} /> по общим знаниям
      </span>
    );
  }
  return null;
}
