import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getLibrary } from "../../api/english";
import type {
  CardJob,
  EnglishCard,
  EnglishEpisode,
  EnglishLibrary,
  EnglishTitle,
  ImportedEpisode,
  LearnSettings,
  LevelFilter,
} from "../../api/english";
import { AssistantLayout } from "../../components/assistant/AssistantLayout";
import { AssistantToggleButton } from "../../components/assistant/AssistantToggleButton";
import { uiSettingsStore } from "../../components/assistant/assistantApi";
import type { AssistantContextProvider } from "../../components/assistant/types";
import { renderEnglishMeta } from "./AssistantCards";
import { EpisodeView } from "./EpisodeView";
import { LearnView } from "./LearnView";
import type { LearnProgress } from "./LearnView";
import { ListeningView } from "./ListeningView";
import { LibraryView } from "./LibraryView";
import { ModuleSettingsDialog } from "./ModuleSettingsDialog";

const SETTINGS_STORAGE_KEY = "nabve.english.learnSettings";
const DEFAULT_SETTINGS: LearnSettings = {
  shuffle: true,
  direction: "en_ru",
  mode: "mixed",
  contextForWords: false,
  contextForExpressions: true,
};

type View =
  | { kind: "library" }
  | { kind: "episode"; title: EnglishTitle; episode: EnglishEpisode; job: CardJob | null }
  | { kind: "learn"; title: EnglishTitle; episode: EnglishEpisode; cards: EnglishCard[]; filter: LevelFilter }
  | { kind: "listening"; title: EnglishTitle; episode: EnglishEpisode };

function loadSettings(): LearnSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<LearnSettings>) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings: LearnSettings): void {
  try {
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch (error) {
    console.error("Failed to persist learn settings:", error);
  }
}

function episodeLabel(title: EnglishTitle, episode: EnglishEpisode): string {
  return `${title.display_name} — ${episode.code}`;
}

const API_BASE = "/api/english";
const PANEL_STORE = uiSettingsStore(API_BASE, "assistant_panel");
const EMPTY_PROGRESS: LearnProgress = { card: null, answered: true, mistakes: [] };

function difficultyChip(title: EnglishTitle | null): string {
  if (!title) {
    return "Справлюсь ли я с этим сериалом/фильмом?";
  }
  return `Справлюсь ли я с этим ${title.kind === "movie" ? "фильмом" : "сериалом"} — «${title.name}»?`;
}

export function EnglishCourse(): JSX.Element {
  const [library, setLibrary] = useState<EnglishLibrary | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>({ kind: "library" });
  const [settings, setSettings] = useState<LearnSettings>(loadSettings);
  const [moduleSettingsOpen, setModuleSettingsOpen] = useState(false);
  const progressRef = useRef<LearnProgress>(EMPTY_PROGRESS);
  const onProgress = useCallback((progress: LearnProgress): void => {
    progressRef.current = progress;
  }, []);

  const provider = useMemo<AssistantContextProvider>(() => {
    const base = { module: "english", apiBase: API_BASE, renderMeta: renderEnglishMeta };
    if (view.kind === "library") {
      return {
        ...base,
        scope: "library",
        scopeId: 0,
        title: "Английский · список папок",
        suggestions: [
          "С какой серии из библиотеки лучше начать?",
          "Что посмотреть на моём уровне?",
          "Чем отличаются уровни B1 и B2?",
          difficultyChip(null),
        ],
        getContext: () => ({ screen: "library" }),
      };
    }
    const { title, episode } = view;
    const label = `${title.display_name} · ${episode.code}`;
    if (view.kind === "learn") {
      return {
        ...base,
        scope: "episode",
        scopeId: episode.id,
        title: `${label} · заучивание`,
        suggestions: [
          "Дай подсказку к текущему слову, но не ответ",
          "Придумай ассоциацию для запоминания",
          "Почему я путаю эти слова?",
          difficultyChip(title),
        ],
        getContext: () => ({
          screen: "learn",
          title_id: title.id,
          episode_id: episode.id,
          card_id: progressRef.current.card?.id ?? null,
          answered: progressRef.current.answered,
          direction: settings.direction,
          mistake_card_ids: progressRef.current.mistakes.map((item) => item.card.id),
        }),
      };
    }
    return {
      ...base,
      scope: "episode",
      scopeId: episode.id,
      title: label,
      suggestions: [
        "Объясни идиомы и фразовые глаголы из этой серии",
        "Какие слова здесь самые полезные?",
        "Составь мини-тест из 5 вопросов",
        difficultyChip(title),
      ],
      getContext: () => ({ screen: "episode", title_id: title.id, episode_id: episode.id }),
    };
  }, [view, settings.direction]);

  const toggle = <AssistantToggleButton />;

  const refresh = useCallback(async (): Promise<void> => {
    try {
      setLibrary(await getLibrary());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить библиотеку.");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function openImported(imported: ImportedEpisode): void {
    void refresh();
    setView({ kind: "episode", title: imported.title, episode: imported.episode, job: imported.job });
  }

  let content: JSX.Element;
  if (view.kind === "learn") {
    content = (
      <LearnView
        episodeId={view.episode.id}
        title={episodeLabel(view.title, view.episode)}
        cards={view.cards}
        settings={settings}
        filter={view.filter}
        headerActions={toggle}
        onProgress={onProgress}
        onExit={() => setView({ kind: "episode", title: view.title, episode: view.episode, job: null })}
      />
    );
  } else if (view.kind === "listening") {
    content = (
      <ListeningView
        episodeId={view.episode.id}
        title={episodeLabel(view.title, view.episode)}
        onExit={() => setView({ kind: "episode", title: view.title, episode: view.episode, job: null })}
      />
    );
  } else if (view.kind === "episode") {
    content = (
      <EpisodeView
        key={view.episode.id}
        title={view.title}
        episode={view.episode}
        initialJob={view.job}
        settings={settings}
        headerActions={toggle}
        onSettingsChange={(next) => {
          setSettings(next);
          saveSettings(next);
        }}
        onBack={() => {
          setView({ kind: "library" });
          void refresh();
        }}
        onLearn={(cards, filter) => setView({ kind: "learn", title: view.title, episode: view.episode, cards, filter })}
        onListening={() => setView({ kind: "listening", title: view.title, episode: view.episode })}
        onChanged={() => void refresh()}
      />
    );
  } else {
    content = (
      <LibraryView
        library={library}
        error={error}
        headerActions={toggle}
        onOpen={(title, episode) => setView({ kind: "episode", title, episode, job: null })}
        onImported={openImported}
        onOpenSettings={() => setModuleSettingsOpen(true)}
        onFiltersChanged={() => void refresh()}
      />
    );
  }

  return (
    <AssistantLayout provider={provider} store={PANEL_STORE}>
      {content}
      {moduleSettingsOpen && (
        <ModuleSettingsDialog onClose={() => setModuleSettingsOpen(false)} onSaved={() => void refresh()} />
      )}
    </AssistantLayout>
  );
}
