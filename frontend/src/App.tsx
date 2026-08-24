import {
  CalendarDays,
  Camera,
  Code2,
  Edit3,
  Gamepad2,
  Image as ImageIcon,
  MessageCircle,
  QrCode,
  Ruler,
  Target,
  User,
  Utensils,
} from "lucide-react";
import { useEffect, useState } from "react";
import { BoardGameImageModal } from "./components/BoardGameImageModal";
import { BoardGamesPanel } from "./components/BoardGamesPanel";
import { CodeAnalysisPanel } from "./components/CodeAnalysisPanel";
import { CollapsibleCard } from "./components/CollapsibleCard";
import { CommandPanel } from "./components/CommandPanel";
import { CustomCommandsPanel } from "./components/CustomCommandsPanel";
import { FitnessChatWidget } from "./components/FitnessChatWidget";
import { FitnessGoalsSection } from "./components/FitnessGoalsSection";
import { FitnessMealDiary } from "./components/FitnessMealDiary";
import { FitnessMeasurementsSection } from "./components/FitnessMeasurementsSection";
import { FitnessPanel } from "./components/FitnessPanel";
import { FitnessProgressPhotoGallery } from "./components/FitnessProgressPhotoGallery";
import { ImageGenerationPanel } from "./components/ImageGenerationPanel";
import { IntegrationsPanel } from "./components/IntegrationsPanel";
import { LanQrPanel } from "./components/LanQrPanel";
import { MessagingPanel } from "./components/MessagingPanel";
import { PlannerView } from "./components/PlannerView";
import { PluginSuggestions } from "./components/PluginSuggestions";
import type { Page } from "./components/Sidebar";
import { Sidebar } from "./components/Sidebar";
import { TextChat } from "./components/TextChat";
import { TextEditingPanel } from "./components/TextEditingPanel";
import { VoiceRecorder } from "./components/VoiceRecorder";
import { VoiceWaveform } from "./components/VoiceWaveform";
import { getStatus } from "./api/client";
import { AssistantAvatar } from "./design/AssistantAvatar";
import { BlobBackdrop } from "./design/BlobBackdrop";
import { GojoOverlay } from "./design/GojoOverlay";
import { DEFAULT_DESIGN_ID } from "./design/registry";
import { ThemeBackdrop } from "./design/ThemeBackdrop";
import type { DesignId } from "./design/types";
import { useGojoEasterEgg } from "./design/useGojoEasterEgg";
import { isElectron } from "./platform/electronAdapter";
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

// Labels for core/voice/module_context.py's active_module_context, shown as
// a small indicator next to the main state label — see App.tsx's status
// polling effect below. Only "fitness" exists today; the map is here (not
// a single hardcoded string) so a future module context (see
// core/voice/module_context.py's own docstring on being a deposit for
// later modules) only needs a new entry, not new indicator plumbing.
const MODULE_CONTEXT_LABELS: Record<string, string> = {
  fitness: "Режим: Фитнес",
};

export function App(): JSX.Element {
  const [activePage, setActivePage] = useState<Page>("assistant");
  const [assistantState, setAssistantState] = useState<AssistantState>("idle");
  const [detail, setDetail] = useState<string>("");
  const [activeModuleContext, setActiveModuleContext] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string>("");
  const [voiceRecording, setVoiceRecording] = useState(false);
  const [voiceSpeaking, setVoiceSpeaking] = useState(false);
  const [designId, setDesignId] = useState<DesignId>(readStoredDesign);
  const {
    convergeTo: gojoConvergeTo,
    merged: gojoMerged,
    notifyConverged: gojoNotifyConverged,
  } = useGojoEasterEgg(designId);
  // Bumped by CommandPanel's onNavigateToGames — forces the Board Games
  // CollapsibleCard open even if the user had collapsed it, so the
  // "Начать шахматы/шашки" shortcut actually reveals the board instead of
  // just switching pages and scrolling to a still-closed card.
  const [gamesOpenSignal, setGamesOpenSignal] = useState(0);

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
          setActiveModuleContext(status.active_module_context);
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
      <BlobBackdrop designId={designId} convergeTo={gojoConvergeTo} onConverged={gojoNotifyConverged} />
      <BoardGameImageModal />
      <div className="app-shell">
        <Sidebar activePage={activePage} onSelect={setActivePage} designId={designId} onDesignChange={handleDesignChange} />

        <div className="app-main">
          <div className={`app-shell__stage${gojoMerged ? " app-shell__stage--gojo" : ""}`}>
            {/* visibility (not display:none) keeps flex flow space
                reserved so the state label/waveforms below don't jump —
                bumped to match GojoOverlay's own footprint while merged
                (its own position:absolute doesn't reserve any space by
                itself, so without this the label would still sit where
                the small 132px avatar used to end, overlapping the much
                bigger overlay). */}
            <div style={gojoMerged ? { visibility: "hidden", minHeight: 300 } : undefined}>
              <AssistantAvatar state={displayState} designId={designId} />
            </div>
            {designId === "eye" && gojoMerged && <GojoOverlay />}
            <div className="app-shell__waveforms">
              <VoiceWaveform mode="listening" active={displayState === "listening"} />
              <VoiceWaveform mode="speaking" active={displayState === "speaking"} />
            </div>
            <div className="app-shell__state-label">{STATE_LABELS[displayState]}</div>
            {activeModuleContext && MODULE_CONTEXT_LABELS[activeModuleContext] && (
              <div className="app-shell__module-context">{MODULE_CONTEXT_LABELS[activeModuleContext]}</div>
            )}
            {detail && <p className="status-detail">{detail}</p>}
            {connectionError && <p className="status-error">{connectionError}</p>}
          </div>

          {activePage === "assistant" ? (
            <div key="assistant" className="app-page">
              <MessagingPanel />

              <VoiceRecorder onRecordingChange={setVoiceRecording} onSpeakingChange={setVoiceSpeaking} />

              <CollapsibleCard title="Текстовый ввод" icon={<MessageCircle size={16} />} accent="blue" defaultOpen>
                <TextChat />
              </CollapsibleCard>

              <CollapsibleCard title="Редактирование текста" icon={<Edit3 size={16} />} accent="purple">
                <TextEditingPanel />
              </CollapsibleCard>

              <CollapsibleCard title="Анализ кода" icon={<Code2 size={16} />} accent="blue">
                <CodeAnalysisPanel />
              </CollapsibleCard>

              <CollapsibleCard title="Планировщик" icon={<CalendarDays size={16} />} accent="amber">
                <PlannerView />
              </CollapsibleCard>

              <CollapsibleCard title="Генерация изображений" icon={<ImageIcon size={16} />} accent="green">
                <ImageGenerationPanel />
              </CollapsibleCard>

              <CollapsibleCard
                title="Настольные игры"
                icon={<Gamepad2 size={16} />}
                accent="red"
                openSignal={gamesOpenSignal}
              >
                <BoardGamesPanel />
              </CollapsibleCard>

              {isElectron() && (
                <CollapsibleCard title="Подключить телефон" icon={<QrCode size={16} />} accent="cyan">
                  <LanQrPanel />
                </CollapsibleCard>
              )}

              <PluginSuggestions />
            </div>
          ) : activePage === "commands" ? (
            <div key="commands" className="app-page">
              <CommandPanel
                onNavigateToGames={() => {
                  setActivePage("assistant");
                  // Deferred to the next tick on purpose — bumping this in
                  // the same update as setActivePage would have the Board
                  // Games CollapsibleCard mount for the first time already
                  // holding the new signal value (it doesn't exist yet
                  // while activePage is "commands"), so its own "did the
                  // signal change since I mounted" check would see no
                  // change and never force itself open. Bumping it once
                  // the card has already mounted with the old value makes
                  // that change visible to it.
                  setTimeout(() => setGamesOpenSignal((n) => n + 1), 0);
                }}
              />
            </div>
          ) : activePage === "my_commands" ? (
            <div key="my_commands" className="app-page">
              <CustomCommandsPanel />
            </div>
          ) : activePage === "fitness" ? (
            <div key="fitness" className="app-page">
              <CollapsibleCard title="Профиль" icon={<User size={16} />} accent="green" defaultOpen>
                <FitnessPanel />
              </CollapsibleCard>

              <CollapsibleCard title="Замеры" icon={<Ruler size={16} />} accent="blue">
                <FitnessMeasurementsSection />
              </CollapsibleCard>

              <CollapsibleCard title="Цели" icon={<Target size={16} />} accent="purple">
                <FitnessGoalsSection />
              </CollapsibleCard>

              <CollapsibleCard title="Дневник питания" icon={<Utensils size={16} />} accent="amber">
                <FitnessMealDiary />
              </CollapsibleCard>

              <CollapsibleCard title="Прогресс-фото" icon={<Camera size={16} />} accent="red">
                <FitnessProgressPhotoGallery />
              </CollapsibleCard>

              <CollapsibleCard title="Чат с помощником" icon={<MessageCircle size={16} />} accent="cyan">
                <FitnessChatWidget />
              </CollapsibleCard>
            </div>
          ) : (
            <div key="integrations" className="app-page">
              <IntegrationsPanel />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
