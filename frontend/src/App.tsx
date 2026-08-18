import { useEffect, useState } from "react";
import { BoardGameImageModal } from "./components/BoardGameImageModal";
import { BoardGamesPanel } from "./components/BoardGamesPanel";
import { CommandPanel } from "./components/CommandPanel";
import { CustomCommandsPanel } from "./components/CustomCommandsPanel";
import { IntegrationsPanel } from "./components/IntegrationsPanel";
import { LanQrPanel } from "./components/LanQrPanel";
import { PersonalityPanel } from "./components/PersonalityPanel";
import { PlannerView } from "./components/PlannerView";
import { PluginSuggestions } from "./components/PluginSuggestions";
import { QuizletPanel } from "./components/QuizletPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { StatusPanel } from "./components/StatusPanel";
import { TextChat } from "./components/TextChat";
import { VoiceRecorder } from "./components/VoiceRecorder";
import { VoiceSettingsPanel } from "./components/VoiceSettingsPanel";
import { VoiceWaveform } from "./components/VoiceWaveform";
import { getStatus } from "./api/client";
import { AssistantAvatar } from "./design/AssistantAvatar";
import { DEFAULT_DESIGN_ID } from "./design/registry";
import { ThemeBackdrop } from "./design/ThemeBackdrop";
import type { DesignId } from "./design/types";
import type { AssistantState } from "./types";
import "./theme.css";
import "./design/themes.css";
import "./App.css";

const DESIGN_STORAGE_KEY = "assistantDesign";

function readStoredDesign(): DesignId {
  try {
    return (window.localStorage.getItem(DESIGN_STORAGE_KEY) as DesignId | null) ?? DEFAULT_DESIGN_ID;
  } catch (error) {
    console.error("Failed to read the stored design from localStorage:", error);
    return DEFAULT_DESIGN_ID;
  }
}

const STATE_LABELS: Record<AssistantState, string> = {
  idle: "Ожидание",
  background_listening: "Жду «привет»",
  listening: "Слушаю",
  processing: "Обработка",
  thinking: "Думаю",
  speaking: "Говорю",
  error: "Ошибка",
  paused: "На паузе",
};

type Tab = "assistant" | "planner" | "commands" | "my_commands" | "learning" | "integrations";

export function App(): JSX.Element {
  const [activeTab, setActiveTab] = useState<Tab>("assistant");
  const [assistantState, setAssistantState] = useState<AssistantState>("idle");
  const [detail, setDetail] = useState<string>("");
  const [connectionError, setConnectionError] = useState<string>("");
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceSpeaking, setVoiceSpeaking] = useState(false);
  const [designId, setDesignId] = useState<DesignId>(readStoredDesign);

  // Re-skins the whole app, not just the avatar — see design/themes.css.
  // html[data-assistant-theme] overrides the same CSS custom properties
  // theme.css defines on :root, so buttons/tabs/corner-brackets/background
  // all pick up each design's palette automatically.
  useEffect(() => {
    document.documentElement.setAttribute("data-assistant-theme", designId);
    return () => document.documentElement.removeAttribute("data-assistant-theme");
  }, [designId]);

  function handleDesignChange(id: DesignId): void {
    setDesignId(id);
    try {
      window.localStorage.setItem(DESIGN_STORAGE_KEY, id);
    } catch (error) {
      // localStorage can be unavailable (e.g. private browsing) — selection
      // still works for the session, it just won't be remembered.
      console.error("Failed to persist the selected design to localStorage:", error);
    }
  }

  // The backend's polled state machine only tracks the always-on desktop
  // voice loop; the browser's on-demand VoiceRecorder is a separate,
  // stateless request/response flow it never sees. Override with local
  // mic/playback activity so the shared orb/waveform still animate for it.
  const displayState: AssistantState = voiceRecording
    ? "listening"
    : voiceSpeaking
      ? "speaking"
      : assistantState;

  useEffect(() => {
    let cancelled = false;

    async function poll(): Promise<void> {
      try {
        const status = await getStatus();
        if (!cancelled) {
          setAssistantState(status.state);
          setDetail(status.detail);
          setConnectionError("");
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to poll /api/status:", error);
          setConnectionError("Нет связи с ядром ассистента");
        }
      }
    }

    void poll();
    const interval = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <>
      <ThemeBackdrop state={displayState} designId={designId} />
      <BoardGameImageModal />
      <div className="app-shell">
        <SettingsPanel designId={designId} onDesignChange={handleDesignChange} />

        <div className="app-shell__stage">
          <AssistantAvatar state={displayState} designId={designId} />
          <div className="app-shell__waveforms">
            <VoiceWaveform mode="listening" active={displayState === "listening"} />
            <VoiceWaveform mode="speaking" active={displayState === "speaking"} />
          </div>
          <div className="app-shell__state-label">{STATE_LABELS[displayState]}</div>
          {detail && <p className="status-detail">{detail}</p>}
          {connectionError && <p className="status-error">{connectionError}</p>}
        </div>

        <div className="app-tabs">
          <button
            className={`app-tabs__button${activeTab === "assistant" ? " app-tabs__button--active" : ""}`}
            onClick={() => setActiveTab("assistant")}
          >
            {"Асси­стент"}
          </button>
          <button
            className={`app-tabs__button${activeTab === "planner" ? " app-tabs__button--active" : ""}`}
            onClick={() => setActiveTab("planner")}
          >
            {"Планиров­щик"}
          </button>
          <button
            className={`app-tabs__button${activeTab === "commands" ? " app-tabs__button--active" : ""}`}
            onClick={() => setActiveTab("commands")}
          >
            Команды
          </button>
          <button
            className={`app-tabs__button${activeTab === "my_commands" ? " app-tabs__button--active" : ""}`}
            onClick={() => setActiveTab("my_commands")}
          >
            Мои команды
          </button>
          <button
            className={`app-tabs__button${activeTab === "learning" ? " app-tabs__button--active" : ""}`}
            onClick={() => setActiveTab("learning")}
          >
            Обучение
          </button>
          <button
            className={`app-tabs__button${activeTab === "integrations" ? " app-tabs__button--active" : ""}`}
            onClick={() => setActiveTab("integrations")}
          >
            {"Интегра­ции"}
          </button>
        </div>

        {activeTab === "assistant" ? (
          <div key="assistant" className="app-tab-content">
            <StatusPanel />

            <VoiceRecorder onRecordingChange={setVoiceRecording} onSpeakingChange={setVoiceSpeaking} />

            <TextChat />

            <BoardGamesPanel />

            <PersonalityPanel />

            <VoiceSettingsPanel />

            <LanQrPanel />

            <PluginSuggestions />
          </div>
        ) : activeTab === "planner" ? (
          <div key="planner" className="app-tab-content">
            <PlannerView />
          </div>
        ) : activeTab === "commands" ? (
          <div key="commands" className="app-tab-content">
            <CommandPanel onNavigateToGames={() => setActiveTab("assistant")} />
          </div>
        ) : activeTab === "my_commands" ? (
          <div key="my_commands" className="app-tab-content">
            <CustomCommandsPanel />
          </div>
        ) : activeTab === "learning" ? (
          <div key="learning" className="app-tab-content">
            <QuizletPanel />
          </div>
        ) : (
          <div key="integrations" className="app-tab-content">
            <IntegrationsPanel />
          </div>
        )}
      </div>
    </>
  );
}
