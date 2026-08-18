import { Fragment, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { GraduationCap, Layers, ListChecks, Mic, Plus, Shuffle, Trash2, type LucideIcon, X } from "lucide-react";
import {
  answerQuizletGame,
  answerQuizletVoiceGame,
  deleteStudySet,
  getQuizletStatus,
  listQuizletLibrary,
  listStudySets,
  quizletImportAllSets,
  quizletImportSet,
  quizletImportSession,
  quizletLogout,
  saveStudySet,
  startQuizletGame,
  startQuizletVoiceGame,
} from "../api/client";
import type { GameMode, QuizletGameState, QuizletLibrarySet, StudySet } from "../types";
import { ConfirmDialog } from "./ConfirmDialog";
import "./QuizletPanel.css";

const MODE_LABELS: Record<GameMode, string> = {
  flashcards: "Карточки",
  learn: "Обучение",
  match: "Сопоставление",
  test: "Тест",
  voice: "Голосовой режим",
};

// Icons per mode, same idea as Quizlet's own mode-switcher (flashcards/
// learn/test/match each get a distinct icon there too) — makes the row
// scannable at a glance instead of five identical-looking text buttons.
const MODE_ICONS: Record<GameMode, LucideIcon> = {
  flashcards: Layers,
  learn: GraduationCap,
  match: Shuffle,
  test: ListChecks,
  voice: Mic,
};

// One accent per mode instead of everything defaulting to --accent-blue —
// same "give each thing its own color" idea as the section-accent borders
// elsewhere in the app.
const MODE_ACCENT: Record<GameMode, string> = {
  flashcards: "var(--accent-blue)",
  learn: "var(--accent-purple)",
  match: "var(--accent-green)",
  test: "var(--accent-amber)",
  voice: "var(--accent-red)",
};

function playAudioBase64(base64: string): void {
  const audio = new Audio(`data:audio/wav;base64,${base64}`);
  void audio.play().catch((error) => console.error("Audio playback failed:", error));
}

// --- Flashcards ------------------------------------------------------------

function FlashcardsView({
  sessionId,
  initialState,
  onExit,
}: {
  sessionId: string;
  initialState: QuizletGameState;
  onExit: () => void;
}): JSX.Element {
  const [state, setState] = useState<QuizletGameState>(initialState);
  const [busy, setBusy] = useState(false);

  async function send(action: string): Promise<void> {
    setBusy(true);
    try {
      const response = await answerQuizletGame(sessionId, { action });
      setState(response.state);
    } catch (error) {
      console.error("Flashcards action failed:", error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="quizlet-game">
      <p className="status-detail">
        {(state.index ?? 0) + 1} / {state.total}
      </p>
      <div
        className={`quizlet-flashcard${state.flipped ? " quizlet-flashcard--flipped" : ""}`}
        onClick={() => void send("flip")}
      >
        <div className="quizlet-flashcard__inner">
          <div className="quizlet-flashcard__face quizlet-flashcard__face--front">{state.term}</div>
          <div className="quizlet-flashcard__face quizlet-flashcard__face--back">{state.definition}</div>
        </div>
      </div>
      <div className="quizlet-game__controls">
        <button type="button" onClick={() => void send("prev")} disabled={busy}>
          Назад
        </button>
        <button type="button" onClick={() => void send("flip")} disabled={busy}>
          Перевернуть
        </button>
        <button type="button" onClick={() => void send("next")} disabled={busy}>
          Дальше
        </button>
      </div>
      <button type="button" className="quizlet-game__exit" onClick={onExit}>
        Выйти
      </button>
    </div>
  );
}

// --- Learn -------------------------------------------------------------

function LearnView({
  sessionId,
  initialState,
  onExit,
}: {
  sessionId: string;
  initialState: QuizletGameState;
  onExit: () => void;
}): JSX.Element {
  const [state, setState] = useState<QuizletGameState>(initialState);
  const [flipped, setFlipped] = useState(false);
  const [busy, setBusy] = useState(false);

  async function answer(known: boolean): Promise<void> {
    if (!state.term_id) {
      return;
    }
    setBusy(true);
    try {
      const response = await answerQuizletGame(sessionId, { term_id: state.term_id, known });
      setState(response.state);
      setFlipped(false);
    } catch (error) {
      console.error("Learn answer failed:", error);
    } finally {
      setBusy(false);
    }
  }

  if (state.finished) {
    return (
      <div className="quizlet-game">
        <p>Все термины этого набора выучены на этой сессии.</p>
        <button type="button" className="quizlet-game__exit" onClick={onExit}>
          Выйти
        </button>
      </div>
    );
  }

  return (
    <div className="quizlet-game">
      <p className="status-detail">
        Осталось: {state.remaining} / {state.total}
      </p>
      <div
        className={`quizlet-flashcard${flipped ? " quizlet-flashcard--flipped" : ""}`}
        onClick={() => setFlipped((prev) => !prev)}
      >
        <div className="quizlet-flashcard__inner">
          <div className="quizlet-flashcard__face quizlet-flashcard__face--front">{state.term}</div>
          <div className="quizlet-flashcard__face quizlet-flashcard__face--back">{state.definition}</div>
        </div>
      </div>
      <div className="quizlet-game__controls">
        <button type="button" onClick={() => void answer(false)} disabled={busy}>
          Не знаю
        </button>
        <button type="button" onClick={() => void answer(true)} disabled={busy}>
          Знаю
        </button>
      </div>
      <button type="button" className="quizlet-game__exit" onClick={onExit}>
        Выйти
      </button>
    </div>
  );
}

// --- Match -------------------------------------------------------------

function MatchView({
  sessionId,
  initialState,
  onExit,
}: {
  sessionId: string;
  initialState: QuizletGameState;
  onExit: () => void;
}): JSX.Element {
  const [state, setState] = useState<QuizletGameState>(initialState);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleTileClick(tileId: string): Promise<void> {
    const tile = state.tiles?.find((t) => t.tile_id === tileId);
    if (!tile || tile.matched || busy) {
      return;
    }
    if (selected === null) {
      setSelected(tileId);
      return;
    }
    if (selected === tileId) {
      setSelected(null);
      return;
    }
    setBusy(true);
    try {
      const response = await answerQuizletGame(sessionId, { first_tile_id: selected, second_tile_id: tileId });
      setState(response.state);
    } catch (error) {
      console.error("Match answer failed:", error);
    } finally {
      setSelected(null);
      setBusy(false);
    }
  }

  if (state.finished) {
    return (
      <div className="quizlet-game">
        <p>Готово! Время: {state.elapsed_seconds} сек.</p>
        <button type="button" className="quizlet-game__exit" onClick={onExit}>
          Выйти
        </button>
      </div>
    );
  }

  return (
    <div className="quizlet-game">
      <p className="status-detail">
        Найдено пар: {state.matched_count} / {state.total}
      </p>
      <div className="quizlet-match__grid">
        {state.tiles?.map((tile) => (
          <button
            key={tile.tile_id}
            type="button"
            className={`quizlet-match__tile${tile.matched ? " quizlet-match__tile--matched" : ""}${
              selected === tile.tile_id ? " quizlet-match__tile--selected" : ""
            }`}
            onClick={() => void handleTileClick(tile.tile_id)}
            disabled={tile.matched || busy}
          >
            {tile.text}
          </button>
        ))}
      </div>
      <button type="button" className="quizlet-game__exit" onClick={onExit}>
        Выйти
      </button>
    </div>
  );
}

// --- Test ----------------------------------------------------------------

function TestView({
  sessionId,
  initialState,
  onExit,
}: {
  sessionId: string;
  initialState: QuizletGameState;
  onExit: () => void;
}): JSX.Element {
  const [state, setState] = useState<QuizletGameState>(initialState);
  const [inputAnswer, setInputAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(payload: Record<string, unknown>): Promise<void> {
    setBusy(true);
    try {
      const response = await answerQuizletGame(sessionId, payload);
      setState(response.state);
      setInputAnswer("");
    } catch (error) {
      console.error("Test answer failed:", error);
    } finally {
      setBusy(false);
    }
  }

  if (state.finished) {
    return (
      <div className="quizlet-game">
        <p>
          Тест завершён: {state.score} / {state.total}
        </p>
        <button type="button" className="quizlet-game__exit" onClick={onExit}>
          Выйти
        </button>
      </div>
    );
  }

  return (
    <div className="quizlet-game">
      <p className="status-detail">
        Вопрос {(state.index ?? 0) + 1} / {state.total} · счёт {state.score}
      </p>
      <p className="quizlet-game__term">{state.term}</p>
      {state.last_answer && (
        <p className={state.last_answer.correct ? "status-detail" : "status-error"}>
          {state.last_answer.correct
            ? "Верно."
            : `Неверно. Правильный ответ: ${state.last_answer.correct_definition}`}
        </p>
      )}
      {state.type === "choice" ? (
        <div className="quizlet-test__options">
          {state.options?.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => void submit({ selected: option })}
              disabled={busy}
            >
              {option}
            </button>
          ))}
        </div>
      ) : (
        <div className="row">
          <input
            type="text"
            value={inputAnswer}
            onChange={(event) => setInputAnswer(event.target.value)}
            placeholder="Введите определение"
          />
          <button
            type="button"
            onClick={() => void submit({ answer: inputAnswer })}
            disabled={busy || !inputAnswer.trim()}
          >
            Ответить
          </button>
        </div>
      )}
      <button type="button" className="quizlet-game__exit" onClick={onExit}>
        Выйти
      </button>
    </div>
  );
}

// --- Voice ---------------------------------------------------------------

function VoiceView({ setId, onExit }: { setId: string; onExit: () => void }): JSX.Element {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [termText, setTermText] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [total, setTotal] = useState(0);
  const [finished, setFinished] = useState(false);
  const [lastResult, setLastResult] = useState<{ correct: boolean; expected: string; transcribed: string } | null>(
    null,
  );
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function start(): Promise<void> {
      try {
        const response = await startQuizletVoiceGame(setId);
        if (cancelled) {
          return;
        }
        setSessionId(response.session_id);
        setTermText(response.term_text);
        setRemaining(response.remaining);
        setTotal(response.total);
        setFinished(response.finished);
        if (response.term_audio_base64) {
          playAudioBase64(response.term_audio_base64);
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        console.error("Failed to start the voice session:", err);
        setError("Не удалось начать голосовую сессию.");
      }
    }

    void start();
    return () => {
      cancelled = true;
    };
  }, [setId]);

  async function startRecording(): Promise<void> {
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Микрофон недоступен в этом браузере.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        void handleRecordingComplete(new Blob(chunksRef.current, { type: recorder.mimeType }));
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch (err) {
      console.error("Failed to access the microphone:", err);
      setError("Не удалось получить доступ к микрофону.");
    }
  }

  function stopRecording(): void {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }

  async function handleRecordingComplete(blob: Blob): Promise<void> {
    if (!sessionId) {
      return;
    }
    setBusy(true);
    try {
      const response = await answerQuizletVoiceGame(sessionId, blob);
      setLastResult({
        correct: response.correct,
        expected: response.expected_definition,
        transcribed: response.transcribed_text,
      });
      setFinished(response.finished);
      setRemaining(response.remaining);
      setTotal(response.total);
      setTermText(response.next_term_text);
      if (response.result_audio_base64) {
        playAudioBase64(response.result_audio_base64);
      }
      if (!response.finished && response.next_term_audio_base64) {
        const nextAudio = response.next_term_audio_base64;
        // Delayed so it doesn't overlap the result line just spoken above.
        window.setTimeout(() => playAudioBase64(nextAudio), 1800);
      }
    } catch (err) {
      console.error("Failed to submit the voice answer:", err);
      setError("Не удалось отправить голосовой ответ.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="quizlet-game quizlet-voice">
      {error && <p className="status-error">{error}</p>}
      {finished ? (
        <p>Голосовая сессия завершена.</p>
      ) : (
        <>
          <p className="status-detail">
            Осталось: {remaining} / {total}
          </p>
          <p className="quizlet-game__term">{termText}</p>
          {lastResult && (
            <p className={lastResult.correct ? "status-detail" : "status-error"}>
              Вы сказали: «{lastResult.transcribed}». {lastResult.correct ? "Верно." : `Правильно: ${lastResult.expected}`}
            </p>
          )}
          <button
            type="button"
            className="quizlet-voice__record"
            onClick={() => void (recording ? stopRecording() : startRecording())}
            disabled={busy || !sessionId}
          >
            {recording ? "Стоп" : busy ? "…" : "Записать ответ"}
          </button>
        </>
      )}
      <button type="button" className="quizlet-game__exit" onClick={onExit}>
        Выйти
      </button>
    </div>
  );
}

// --- Manual set form -------------------------------------------------------

interface TermFormRow {
  term: string;
  definition: string;
}

interface SetFormState {
  title: string;
  terms: TermFormRow[];
}

const EMPTY_SET_FORM: SetFormState = { title: "", terms: [{ term: "", definition: "" }] };

// --- Root panel --------------------------------------------------------

export function QuizletPanel(): JSX.Element {
  const [loggedIn, setLoggedIn] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [sets, setSets] = useState<StudySet[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  // null = "haven't observed a status yet" — the very first check (whatever
  // it finds) is a baseline, not a fresh login, so it must not itself count
  // as a false->true transition below.
  const wasLoggedInRef = useRef<boolean | null>(null);
  const [bulkImporting, setBulkImporting] = useState(false);
  const [bulkImportMessage, setBulkImportMessage] = useState("");

  const [libraryOpen, setLibraryOpen] = useState(false);
  const [library, setLibrary] = useState<QuizletLibrarySet[] | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState("");
  const [importingId, setImportingId] = useState<string | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingSet, setEditingSet] = useState<StudySet | null>(null);
  const [form, setForm] = useState<SetFormState>(EMPTY_SET_FORM);
  const [saving, setSaving] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<StudySet | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [selectedSet, setSelectedSet] = useState<StudySet | null>(null);
  const [viewingSet, setViewingSet] = useState<StudySet | null>(null);
  const [activeMode, setActiveMode] = useState<GameMode | null>(null);
  const [activeSession, setActiveSession] = useState<{ sessionId: string; state: QuizletGameState } | null>(null);
  const [startingMode, setStartingMode] = useState(false);

  async function refreshSets(): Promise<void> {
    try {
      setSets(await listStudySets());
    } catch (err) {
      console.error("Failed to reload study sets:", err);
    }
  }

  // Fires once per fresh login (Войти или Импорт из браузера — whichever
  // gets there first) — not on every poll tick, and not for a session that
  // was already logged in when the panel mounted (see wasLoggedInRef).
  // Pulls the whole Quizlet library into local storage in one go and closes
  // the browser tab, so the user doesn't have to open "Библиотека Quizlet"
  // and import sets one at a time by hand.
  async function handleLoggedInChange(nowLoggedIn: boolean): Promise<void> {
    const wasLoggedIn = wasLoggedInRef.current;
    wasLoggedInRef.current = nowLoggedIn;
    setLoggedIn(nowLoggedIn);
    if (wasLoggedIn !== false || !nowLoggedIn) {
      return;
    }
    setBulkImporting(true);
    setBulkImportMessage("");
    try {
      const response = await quizletImportAllSets();
      setBulkImportMessage(response.message || "");
      await refreshSets();
    } catch (err) {
      console.error("Failed to bulk-import the Quizlet library:", err);
      setBulkImportMessage("Не удалось автоматически перенести библиотеку — попробуйте «Библиотека Quizlet» вручную.");
    } finally {
      setBulkImporting(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [status, setsList] = await Promise.all([getQuizletStatus(), listStudySets()]);
        if (cancelled) {
          return;
        }
        wasLoggedInRef.current = status.logged_in; // baseline — not a transition
        setLoggedIn(status.logged_in);
        setSets(setsList);
        setLoaded(true);
      } catch (err) {
        if (cancelled) {
          return;
        }
        console.error("Failed to load the Обучение tab:", err);
        setError("Не удалось загрузить наборы.");
      }
    }

    void load();
    const interval = window.setInterval(() => {
      void getQuizletStatus()
        .then((status) => {
          if (!cancelled) {
            void handleLoggedInChange(status.logged_in);
          }
        })
        .catch((err) => console.error("Failed to poll Quizlet status:", err));
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  async function handleLogout(): Promise<void> {
    setAuthBusy(true);
    try {
      await quizletLogout();
      setLoggedIn(false);
      setLibrary(null);
      setLibraryOpen(false);
    } catch (err) {
      console.error("Failed to log out of Quizlet:", err);
      setError(err instanceof Error ? err.message : "Не удалось выйти из Quizlet.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleImportSession(): Promise<void> {
    setAuthBusy(true);
    setError("");
    try {
      const response = await quizletImportSession();
      if (response.status === "failed") {
        setError(response.message || "Не удалось импортировать сессию.");
        return;
      }
      await handleLoggedInChange(true);
    } catch (err) {
      console.error("Failed to import a Quizlet browser session:", err);
      setError(err instanceof Error ? err.message : "Не удалось импортировать сессию.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function toggleLibrary(): Promise<void> {
    if (libraryOpen) {
      setLibraryOpen(false);
      return;
    }
    setLibraryOpen(true);
    setLibraryLoading(true);
    setLibraryError("");
    try {
      setLibrary(await listQuizletLibrary());
    } catch (err) {
      console.error("Failed to load the Quizlet library:", err);
      setLibraryError(err instanceof Error ? err.message : "Не удалось загрузить библиотеку Quizlet.");
    } finally {
      setLibraryLoading(false);
    }
  }

  async function handleImport(item: QuizletLibrarySet): Promise<void> {
    setImportingId(item.quizlet_set_id);
    setLibraryError("");
    try {
      await quizletImportSet(item.quizlet_set_id, item.title);
      await refreshSets();
      setLibrary(await listQuizletLibrary());
    } catch (err) {
      console.error("Failed to import the Quizlet set:", err);
      setLibraryError(err instanceof Error ? err.message : `Не удалось импортировать набор «${item.title}».`);
    } finally {
      setImportingId(null);
    }
  }

  function openCreateForm(): void {
    setForm(EMPTY_SET_FORM);
    setEditingSet(null);
    setFormOpen(true);
  }

  function openEditForm(set: StudySet): void {
    setForm({
      title: set.title,
      terms: set.terms.length > 0 ? set.terms.map((t) => ({ term: t.term, definition: t.definition })) : [{ term: "", definition: "" }],
    });
    setEditingSet(set);
    setFormOpen(true);
  }

  function closeForm(): void {
    setFormOpen(false);
    setEditingSet(null);
    setForm(EMPTY_SET_FORM);
  }

  function updateFormRow(index: number, field: "term" | "definition", value: string): void {
    setForm((prev) => ({
      ...prev,
      terms: prev.terms.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    }));
  }

  function addFormRow(): void {
    setForm((prev) => ({ ...prev, terms: [...prev.terms, { term: "", definition: "" }] }));
  }

  function removeFormRow(index: number): void {
    setForm((prev) => ({ ...prev, terms: prev.terms.filter((_, i) => i !== index) }));
  }

  const formReady = form.title.trim() !== "" && form.terms.some((row) => row.term.trim() && row.definition.trim());

  async function handleSubmitForm(): Promise<void> {
    if (!formReady) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const pairs = form.terms
        .filter((row) => row.term.trim() && row.definition.trim())
        .map((row) => ({ term: row.term.trim(), definition: row.definition.trim() }));
      await saveStudySet(editingSet?.id, form.title.trim(), pairs);
      closeForm();
      await refreshSets();
    } catch (err) {
      console.error("Failed to save the study set:", err);
      setError("Не удалось сохранить набор.");
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirmDelete(): Promise<void> {
    if (!confirmingDelete) {
      return;
    }
    setDeleting(true);
    try {
      await deleteStudySet(confirmingDelete.id);
      if (selectedSet?.id === confirmingDelete.id) {
        setSelectedSet(null);
      }
      setConfirmingDelete(null);
      await refreshSets();
    } catch (err) {
      console.error("Failed to delete the study set:", err);
      setError("Не удалось удалить набор.");
    } finally {
      setDeleting(false);
    }
  }

  function selectSet(set: StudySet): void {
    setSelectedSet(set);
    setActiveMode(null);
    setActiveSession(null);
  }

  // Double-click on a set card — like opening a folder to see what's
  // inside, rather than single-click's "select this set to study."
  function openSetContents(set: StudySet): void {
    setViewingSet(set);
  }

  async function startMode(mode: GameMode): Promise<void> {
    if (!selectedSet) {
      return;
    }
    setStartingMode(true);
    setError("");
    try {
      if (mode === "voice") {
        setActiveMode(mode);
        setActiveSession(null);
      } else {
        const response = await startQuizletGame(selectedSet.id, mode);
        setActiveMode(mode);
        setActiveSession({ sessionId: response.session_id, state: response.state });
      }
    } catch (err) {
      console.error("Failed to start the game mode:", err);
      setError("Не удалось начать этот режим — возможно, в наборе нет терминов.");
    } finally {
      setStartingMode(false);
    }
  }

  function exitMode(): void {
    setActiveMode(null);
    setActiveSession(null);
    void refreshSets();
  }

  return (
    <div className="section quizlet-panel">
      <h3>Обучение</h3>
      {error && <p className="status-error">{error}</p>}
      {bulkImporting && <p className="status-detail">Переношу всю библиотеку Quizlet в NABVE…</p>}
      {!bulkImporting && bulkImportMessage && <p className="status-detail">{bulkImportMessage}</p>}
      {!loaded && !error && <p className="status-detail">Загрузка…</p>}

      <div className="quizlet-panel__auth">
        <div className="quizlet-panel__auth-info">
          <span className={`quizlet-panel__auth-status${loggedIn ? " quizlet-panel__auth-status--authed" : ""}`}>
            {loggedIn ? "Подключено к Quizlet" : "Не подключено к Quizlet"}
          </span>
          {!loggedIn && (
            <p className="status-detail">
              1. Зайдите на quizlet.com в своём обычном браузере (Chrome, Firefox — тот, которым обычно пользуетесь)
              и войдите в свой аккаунт, как всегда.
              <br />
              2. Вернитесь сюда и нажмите «Связь с браузером» — NABVE скопирует эту сессию (куки) в свою, без пароля.
            </p>
          )}
        </div>
        <div className="quizlet-panel__auth-actions">
          {loggedIn ? (
            <>
              <button type="button" onClick={() => void handleLogout()} disabled={authBusy}>
                {authBusy ? "…" : "Выйти из Quizlet"}
              </button>
              <button type="button" onClick={() => void toggleLibrary()}>
                {libraryOpen ? "Скрыть библиотеку" : "Библиотека Quizlet"}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="quizlet-panel__import-session"
              onClick={() => void handleImportSession()}
              disabled={authBusy}
            >
              {authBusy ? "…" : "Связь с браузером"}
            </button>
          )}
        </div>
      </div>

      {libraryOpen && (
        <div className="quizlet-panel__library">
          {libraryLoading && <p className="status-detail">Загрузка библиотеки…</p>}
          {libraryError && <p className="status-error">{libraryError}</p>}
          {!libraryLoading && library && library.length === 0 && (
            <p className="status-detail">В библиотеке Quizlet пока нет наборов.</p>
          )}
          {library?.map((item) => (
            <div key={item.quizlet_set_id} className="quizlet-panel__library-row">
              <span>
                {item.title} <span className="status-detail">({item.term_count} терминов)</span>
              </span>
              <button
                type="button"
                onClick={() => void handleImport(item)}
                disabled={importingId === item.quizlet_set_id}
              >
                {importingId === item.quizlet_set_id
                  ? "…"
                  : item.already_imported
                    ? "Обновить"
                    : "Импортировать"}
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="quizlet-panel__list-header">
        <span className="custom-commands-panel__subheading">Мои наборы</span>
        <button type="button" className="custom-commands-panel__add" onClick={openCreateForm} title="Создать набор">
          <Plus size={18} />
        </button>
      </div>

      {loaded && sets.length === 0 && <p className="status-detail">Наборов пока нет.</p>}

      <div className="quizlet-panel__cards">
        {sets.map((set) => (
          <Fragment key={set.id}>
            <div
              className={`quizlet-panel__card${selectedSet?.id === set.id ? " quizlet-panel__card--active" : ""}`}
            >
              <button
                type="button"
                className="quizlet-panel__card-main"
                onClick={() => selectSet(set)}
                onDoubleClick={() => openSetContents(set)}
                title="Клик — выбрать для изучения, двойной клик — открыть содержимое"
              >
                <span className="quizlet-panel__card-title">{set.title}</span>
                <span className="status-detail">
                  {set.terms.length} терминов · {set.progress_percent}% выучено · {set.attempts_count} попыток
                  {set.source === "quizlet_import" ? " · из Quizlet" : ""}
                </span>
              </button>
              <div className="quizlet-panel__card-actions">
                {set.source === "manual" && (
                  <button type="button" onClick={() => openEditForm(set)} title="Редактировать">
                    Изменить
                  </button>
                )}
                <button type="button" onClick={() => setConfirmingDelete(set)} title="Удалить">
                  <Trash2 size={16} />
                </button>
              </div>
            </div>

            {/* Rendered right under the card it belongs to, not after the
                whole list — so studying the set you just clicked doesn't
                mean scrolling past every other set first. */}
            {selectedSet?.id === set.id && (
              <div className="quizlet-panel__study">
                <h4>{selectedSet.title}</h4>
                {activeMode === null ? (
                  <div className="quizlet-panel__modes">
                    {(Object.keys(MODE_LABELS) as GameMode[]).map((mode) => {
                      const Icon = MODE_ICONS[mode];
                      return (
                        <button
                          type="button"
                          key={mode}
                          className="quizlet-panel__mode"
                          style={{ "--mode-accent": MODE_ACCENT[mode] } as CSSProperties}
                          onClick={() => void startMode(mode)}
                          disabled={startingMode}
                        >
                          <Icon size={20} />
                          <span>{MODE_LABELS[mode]}</span>
                        </button>
                      );
                    })}
                  </div>
                ) : activeMode === "voice" ? (
                  <VoiceView setId={selectedSet.id} onExit={exitMode} />
                ) : activeSession ? (
                  activeMode === "flashcards" ? (
                    <FlashcardsView
                      sessionId={activeSession.sessionId}
                      initialState={activeSession.state}
                      onExit={exitMode}
                    />
                  ) : activeMode === "learn" ? (
                    <LearnView sessionId={activeSession.sessionId} initialState={activeSession.state} onExit={exitMode} />
                  ) : activeMode === "match" ? (
                    <MatchView sessionId={activeSession.sessionId} initialState={activeSession.state} onExit={exitMode} />
                  ) : (
                    <TestView sessionId={activeSession.sessionId} initialState={activeSession.state} onExit={exitMode} />
                  )
                ) : null}
              </div>
            )}
          </Fragment>
        ))}
      </div>

      {viewingSet && (
        <div className="quizlet-panel__contents">
          <div className="quizlet-panel__contents-header">
            <h4>{viewingSet.title}</h4>
            <button type="button" onClick={() => setViewingSet(null)} title="Закрыть">
              <X size={16} />
            </button>
          </div>
          {viewingSet.terms.length === 0 ? (
            <p className="status-detail">В этом наборе пока нет терминов.</p>
          ) : (
            <div className="quizlet-panel__contents-list">
              {viewingSet.terms.map((term) => (
                <div key={term.id} className="quizlet-panel__contents-row">
                  <span className="quizlet-panel__contents-term">{term.term}</span>
                  <span className="quizlet-panel__contents-definition">{term.definition}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {formOpen && (
        <ConfirmDialog
          title={editingSet ? "Редактировать набор" : "Новый набор"}
          message="Добавьте пары термин / определение."
          tone="neutral"
          confirmLabel={editingSet ? "Сохранить" : "Создать набор"}
          busy={saving}
          confirmDisabled={!formReady}
          onCancel={closeForm}
          onConfirm={() => void handleSubmitForm()}
        >
          <div className="command-panel__form-fields">
            <label className="command-panel__form-field">
              <span>Название набора</span>
              <input
                type="text"
                value={form.title}
                onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
              />
            </label>

            <div className="quizlet-panel__form-terms">
              {form.terms.map((row, index) => (
                <div key={index} className="quizlet-panel__form-term-row">
                  <input
                    type="text"
                    value={row.term}
                    placeholder="Термин"
                    onChange={(event) => updateFormRow(index, "term", event.target.value)}
                  />
                  <input
                    type="text"
                    value={row.definition}
                    placeholder="Определение"
                    onChange={(event) => updateFormRow(index, "definition", event.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => removeFormRow(index)}
                    disabled={form.terms.length <= 1}
                    title="Удалить пару"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
            <button type="button" onClick={addFormRow}>
              + Добавить пару
            </button>
          </div>
        </ConfirmDialog>
      )}

      {confirmingDelete && (
        <ConfirmDialog
          title="Удалить набор?"
          message={`Набор «${confirmingDelete.title}» будет удалён без возможности восстановления.`}
          tone="danger"
          confirmLabel="Удалить"
          busy={deleting}
          onCancel={() => setConfirmingDelete(null)}
          onConfirm={() => void handleConfirmDelete()}
        />
      )}
    </div>
  );
}
