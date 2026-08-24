import { Settings as SettingsIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createPortal } from "react-dom";
import { getProfileFact, runCommand, saveAboutMe, setProfileFact } from "../api/client";
import { DESIGNS } from "../design/registry";
import { PersonalityPanel } from "./PersonalityPanel";
import { VoiceSettingsPanel } from "./VoiceSettingsPanel";
import type { DesignId } from "../design/types";
import "./SettingsPanel.css";

const ASSISTANT_NAME_KEY = "assistant_name";
const ABOUT_ME_KEY = "about_me";
// Matches modules/user_profile/domain.py's GENDER_KEY/DEFAULT_GENDER exactly.
const GENDER_KEY = "gender";
type Gender = "male" | "female";
const DEFAULT_GENDER: Gender = "male";
const CLAUDE_LOGIN_POLL_MS = 3000;
const CLAUDE_LOGIN_POLL_MAX_ATTEMPTS = 40; // ~2 minutes

type SettingsTab = "design" | "profile" | "voice" | "personality" | "code";

interface ClaudeAuthStatus {
  loggedIn: boolean;
  email: string | undefined;
  error: string | undefined;
}

interface SettingsPanelProps {
  designId: DesignId;
  onDesignChange: (id: DesignId) => void;
}

export function SettingsPanel({ designId, onDesignChange }: SettingsPanelProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<SettingsTab>("design");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");

  const [nameInput, setNameInput] = useState("");
  const [savedName, setSavedName] = useState("");
  const [nameStatus, setNameStatus] = useState("");

  const [aboutInput, setAboutInput] = useState("");
  const [savedAbout, setSavedAbout] = useState("");
  const [aboutStatus, setAboutStatus] = useState("");
  const [savingAbout, setSavingAbout] = useState(false);

  const [gender, setGender] = useState<Gender>(DEFAULT_GENDER);
  const [savingGender, setSavingGender] = useState(false);

  const [claudeStatus, setClaudeStatus] = useState<ClaudeAuthStatus | null>(null);
  const [claudeChecking, setClaudeChecking] = useState(false);
  const [claudeLoggingIn, setClaudeLoggingIn] = useState(false);
  const claudePollTimeout = useRef<number | null>(null);

  useEffect(() => {
    if (!open || loaded) {
      return;
    }
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const [name, about, genderFact] = await Promise.all([
          getProfileFact(ASSISTANT_NAME_KEY),
          getProfileFact(ABOUT_ME_KEY),
          getProfileFact(GENDER_KEY),
        ]);
        if (cancelled) {
          return;
        }
        setNameInput(name ?? "");
        setSavedName(name ?? "");
        setAboutInput(about ?? "");
        setSavedAbout(about ?? "");
        setGender(genderFact === "female" ? "female" : DEFAULT_GENDER);
        setLoaded(true);
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load profile settings:", error);
          setError("Не удалось загрузить настройки профиля.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [open, loaded]);

  async function checkClaudeStatus(): Promise<ClaudeAuthStatus> {
    const response = await runCommand("claude_cli_status");
    const result = (response.result ?? {}) as Partial<ClaudeAuthStatus>;
    const status: ClaudeAuthStatus = {
      loggedIn: Boolean(result.loggedIn),
      email: typeof result.email === "string" ? result.email : undefined,
      error: typeof result.error === "string" ? result.error : undefined,
    };
    setClaudeStatus(status);
    return status;
  }

  useEffect(() => {
    if (!open || tab !== "code" || claudeStatus !== null) {
      return;
    }
    setClaudeChecking(true);
    checkClaudeStatus()
      .catch((error) => {
        console.error("Failed to check Claude Code CLI status:", error);
        setClaudeStatus({ loggedIn: false, email: undefined, error: "Не удалось проверить статус." });
      })
      .finally(() => setClaudeChecking(false));
  }, [open, tab, claudeStatus]);

  useEffect(() => {
    return () => {
      if (claudePollTimeout.current !== null) {
        window.clearTimeout(claudePollTimeout.current);
      }
    };
  }, []);

  function pollClaudeStatusUntilLoggedIn(attempt = 0): void {
    if (attempt >= CLAUDE_LOGIN_POLL_MAX_ATTEMPTS) {
      setClaudeLoggingIn(false);
      return;
    }
    claudePollTimeout.current = window.setTimeout(() => {
      checkClaudeStatus()
        .then((status) => {
          if (status.loggedIn) {
            setClaudeLoggingIn(false);
          } else {
            pollClaudeStatusUntilLoggedIn(attempt + 1);
          }
        })
        .catch(() => pollClaudeStatusUntilLoggedIn(attempt + 1));
    }, CLAUDE_LOGIN_POLL_MS);
  }

  async function handleClaudeLogin(): Promise<void> {
    setClaudeLoggingIn(true);
    try {
      await runCommand("claude_cli_login");
      pollClaudeStatusUntilLoggedIn();
    } catch (error) {
      console.error("Failed to start Claude Code CLI login:", error);
      setClaudeLoggingIn(false);
    }
  }

  async function handleSaveName(): Promise<void> {
    const trimmed = nameInput.trim();
    if (!trimmed) {
      return;
    }
    setNameStatus("");
    try {
      await setProfileFact(ASSISTANT_NAME_KEY, trimmed);
      setSavedName(trimmed);
      setNameStatus("Сохранено.");
    } catch (error) {
      console.error("Failed to save the assistant name:", error);
      setNameStatus("Не удалось сохранить имя.");
    }
  }

  async function handleSaveAbout(): Promise<void> {
    const trimmed = aboutInput.trim();
    if (!trimmed) {
      return;
    }
    setSavingAbout(true);
    setAboutStatus("");
    try {
      const extractedKeys = await saveAboutMe(trimmed);
      setSavedAbout(trimmed);
      setAboutStatus(
        extractedKeys.length > 0
          ? `Запомнил (выделил ${extractedKeys.length} факт(а/ов): ${extractedKeys.join(", ")}).`
          : "Запомнил дословно.",
      );
    } catch (error) {
      console.error("Failed to save the about-me text:", error);
      setAboutStatus("Не удалось сохранить.");
    } finally {
      setSavingAbout(false);
    }
  }

  async function handleGenderChange(next: Gender): Promise<void> {
    setSavingGender(true);
    setError("");
    try {
      await setProfileFact(GENDER_KEY, next);
      setGender(next);
    } catch (error) {
      console.error("Failed to save the gender setting:", error);
      setError("Не удалось сохранить обращение.");
    } finally {
      setSavingGender(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="sidebar__item settings-gear"
        style={{ "--item-accent": "var(--glow-listening)" } as CSSProperties}
        onClick={() => setOpen(true)}
      >
        <span className="sidebar__item-icon" aria-hidden="true">
          <SettingsIcon size={20} />
        </span>
        <span className="sidebar__item-label">Настройки ассистента</span>
      </button>

      {open &&
        createPortal(
          <div className="settings-overlay" role="dialog" aria-modal="true" aria-label="Настройки">
            {/* Decorative click-outside-to-close target, not a semantic control. */}
            {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
            <div className="settings-overlay__backdrop" onClick={() => setOpen(false)} />
          <div className="settings-panel">
            <div className="settings-panel__header">
              <h2>Настройки</h2>
              <button
                type="button"
                className="settings-panel__close"
                onClick={() => setOpen(false)}
                aria-label="Закрыть настройки"
              >
                ×
              </button>
            </div>

            <div className="settings-panel__tabs">
              <button
                type="button"
                className={`settings-panel__tab${tab === "design" ? " settings-panel__tab--active" : ""}`}
                onClick={() => setTab("design")}
              >
                Дизайн
              </button>
              <button
                type="button"
                className={`settings-panel__tab${tab === "profile" ? " settings-panel__tab--active" : ""}`}
                onClick={() => setTab("profile")}
              >
                Профиль
              </button>
              <button
                type="button"
                className={`settings-panel__tab${tab === "voice" ? " settings-panel__tab--active" : ""}`}
                onClick={() => setTab("voice")}
              >
                Голос
              </button>
              <button
                type="button"
                className={`settings-panel__tab${tab === "personality" ? " settings-panel__tab--active" : ""}`}
                onClick={() => setTab("personality")}
              >
                Личность
              </button>
              <button
                type="button"
                className={`settings-panel__tab${tab === "code" ? " settings-panel__tab--active" : ""}`}
                onClick={() => setTab("code")}
              >
                Генерация кода
              </button>
            </div>

            {error && <p className="status-error">{error}</p>}

            {tab === "design" ? (
              <div className="settings-panel__design-grid">
                {DESIGNS.map((design) => {
                  const Component = design.Component;
                  const active = design.id === designId;
                  return (
                    // A <div role="button"> rather than a real <button>: some
                    // design previews (the clown's nose) render their own
                    // interactive <button> internally, and a <button> can't
                    // legally contain another <button> in the DOM.
                    <div
                      key={design.id}
                      role="button"
                      tabIndex={0}
                      className={`design-card${active ? " design-card--active" : ""}`}
                      onClick={() => onDesignChange(design.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onDesignChange(design.id);
                        }
                      }}
                      title={design.description}
                    >
                      <span className="design-card__preview" aria-hidden="true">
                        <Component state="idle" />
                      </span>
                      <span className="design-card__name">{design.name}</span>
                      <span className="design-card__tagline">{design.tagline}</span>
                    </div>
                  );
                })}
              </div>
            ) : tab === "profile" ? (
              <div className="settings-panel__profile">
                {!loaded && !error && <p className="status-detail">Загрузка…</p>}

                <div className="settings-panel__field">
                  <span className="settings-panel__label">Имя ассистента</span>
                  <div className="row">
                    <input
                      type="text"
                      value={nameInput}
                      onChange={(event) => setNameInput(event.target.value)}
                      placeholder="Как называть себя"
                    />
                    <button
                      type="button"
                      onClick={() => void handleSaveName()}
                      disabled={!nameInput.trim() || nameInput.trim() === savedName}
                    >
                      Сохранить
                    </button>
                  </div>
                  {nameStatus && <p className="status-detail">{nameStatus}</p>}
                </div>

                <div className="settings-panel__field">
                  <span className="settings-panel__label">О себе</span>
                  <textarea
                    className="settings-panel__about-input"
                    value={aboutInput}
                    onChange={(event) => setAboutInput(event.target.value)}
                    placeholder="Расскажи о себе — ассистент запомнит это"
                    rows={5}
                  />
                  <div className="row">
                    <button
                      type="button"
                      onClick={() => void handleSaveAbout()}
                      disabled={savingAbout || !aboutInput.trim() || aboutInput.trim() === savedAbout}
                    >
                      {savingAbout ? "Запоминаю…" : "Запомнить"}
                    </button>
                  </div>
                  {aboutStatus && <p className="status-detail">{aboutStatus}</p>}
                </div>

                <div className="settings-panel__field">
                  <span className="settings-panel__label">Обращение</span>
                  <div className="row">
                    <label className="settings-panel__radio">
                      <input
                        type="radio"
                        name="gender"
                        checked={gender === "male"}
                        disabled={savingGender}
                        onChange={() => void handleGenderChange("male")}
                      />
                      Сэр (мужской)
                    </label>
                    <label className="settings-panel__radio">
                      <input
                        type="radio"
                        name="gender"
                        checked={gender === "female"}
                        disabled={savingGender}
                        onChange={() => void handleGenderChange("female")}
                      />
                      Мэм (женский)
                    </label>
                  </div>
                </div>
              </div>
            ) : tab === "voice" ? (
              <VoiceSettingsPanel />
            ) : tab === "personality" ? (
              <PersonalityPanel />
            ) : tab === "code" ? (
              <div className="settings-panel__profile">
                <div className="settings-panel__field">
                  <span className="settings-panel__label">Подключение Claude для генерации кода</span>
                  <p className="status-detail">
                    Единая точка правды для генерации кода в проекте (плагины, PHP-фиксы и т.д.) — Claude Code CLI.
                    Если он уже авторизован на этой машине (например, из сессии PyCharm), отдельный вход не нужен.
                  </p>
                  {claudeChecking && !claudeStatus && <p className="status-detail">Проверяю статус…</p>}
                  {claudeStatus && (
                    <p className={claudeStatus.loggedIn ? "settings-panel__success" : "status-error"}>
                      {claudeStatus.loggedIn
                        ? `Claude подключён${claudeStatus.email ? ` (${claudeStatus.email})` : ""}`
                        : `Claude не подключён — генерация кода недоступна${claudeStatus.error ? ` (${claudeStatus.error})` : ""}`}
                    </p>
                  )}
                  {claudeStatus && !claudeStatus.loggedIn && (
                    <div className="row">
                      <button type="button" onClick={() => void handleClaudeLogin()} disabled={claudeLoggingIn}>
                        {claudeLoggingIn ? "Ожидаю вход в браузере…" : "Войти в Claude"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ) : null}
          </div>
          </div>,
          document.body,
        )}
    </>
  );
}
