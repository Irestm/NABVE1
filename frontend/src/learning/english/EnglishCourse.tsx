import { useCallback, useEffect, useState } from "react";
import { getLibrary } from "../../api/english";
import type {
  CardJob,
  EnglishCard,
  EnglishEpisode,
  EnglishLibrary,
  EnglishSeries,
  ImportedEpisode,
  LearnSettings,
} from "../../api/english";
import { EpisodeView } from "./EpisodeView";
import { LearnView } from "./LearnView";
import { LibraryView } from "./LibraryView";

const SETTINGS_STORAGE_KEY = "nabve.english.learnSettings";
const DEFAULT_SETTINGS: LearnSettings = { shuffle: true, direction: "en_ru", mode: "mixed" };

type View =
  | { kind: "library" }
  | { kind: "episode"; series: EnglishSeries; episode: EnglishEpisode; job: CardJob | null }
  | { kind: "learn"; series: EnglishSeries; episode: EnglishEpisode; cards: EnglishCard[] };

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

export function EnglishCourse(): JSX.Element {
  const [library, setLibrary] = useState<EnglishLibrary | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>({ kind: "library" });
  const [settings, setSettings] = useState<LearnSettings>(loadSettings);

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
    setView({ kind: "episode", series: imported.series, episode: imported.episode, job: imported.job });
  }

  if (view.kind === "learn") {
    return (
      <LearnView
        episodeId={view.episode.id}
        title={view.episode.display_name || `${view.series.title} — ${view.episode.code}`}
        cards={view.cards}
        settings={settings}
        onExit={() => setView({ kind: "episode", series: view.series, episode: view.episode, job: null })}
      />
    );
  }

  if (view.kind === "episode") {
    return (
      <EpisodeView
        key={view.episode.id}
        seriesTitle={view.series.title}
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
        onLearn={(cards) => setView({ kind: "learn", series: view.series, episode: view.episode, cards })}
        onChanged={() => void refresh()}
      />
    );
  }

  return (
    <LibraryView
      library={library}
      error={error}
      onOpen={(series, episode) => setView({ kind: "episode", series, episode, job: null })}
      onImported={openImported}
    />
  );
}
