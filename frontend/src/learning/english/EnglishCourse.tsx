import { useCallback, useEffect, useState } from "react";
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
import { EpisodeView } from "./EpisodeView";
import { LearnView } from "./LearnView";
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

export function EnglishCourse(): JSX.Element {
  const [library, setLibrary] = useState<EnglishLibrary | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>({ kind: "library" });
  const [settings, setSettings] = useState<LearnSettings>(loadSettings);
  const [moduleSettingsOpen, setModuleSettingsOpen] = useState(false);

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
        onOpen={(title, episode) => setView({ kind: "episode", title, episode, job: null })}
        onImported={openImported}
        onOpenSettings={() => setModuleSettingsOpen(true)}
        onFiltersChanged={() => void refresh()}
      />
    );
  }

  return (
    <>
      {content}
      {moduleSettingsOpen && (
        <ModuleSettingsDialog onClose={() => setModuleSettingsOpen(false)} onSaved={() => void refresh()} />
      )}
    </>
  );
}
