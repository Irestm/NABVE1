import type { ProviderName } from "../types";
import "./ProviderCard.css";

interface ProviderCardProps {
  provider: ProviderName;
  active: boolean;
  limited: boolean;
  loggedIn: boolean;
  busy: boolean;
  onLogin: () => void;
  onLogout: () => void;
  onImportSession: () => void;
}

interface ProviderMeta {
  label: string;
  description: string;
  initial: string;
  // Where the user actually logs in by hand — shown next to the import
  // button so "Импорт из браузера" isn't a mystery action (see the note
  // rendered below it).
  loginSite: string;
}

// Not the providers' official logos — trademark/licensing status of each
// varies and isn't worth chasing for a single-user local app; a
// consistent, theme-following monogram badge reads fine at this size and
// never goes stale when a vendor redesigns their logo.
const PROVIDER_META: Record<ProviderName, ProviderMeta> = {
  gemini: {
    label: "Gemini",
    description: "Быстрый и точный, хорош для повседневных задач и быстрых ответов",
    initial: "G",
    loginSite: "gemini.google.com",
  },
  chatgpt: {
    label: "ChatGPT",
    description: "Сильный в рассуждениях и написании текста, второй по приоритету",
    initial: "C",
    loginSite: "chatgpt.com",
  },
  deepseek: {
    label: "DeepSeek",
    description: "Хорош в коде и технических задачах, запасной вариант",
    initial: "D",
    loginSite: "chat.deepseek.com",
  },
  grok: {
    label: "Grok",
    description: "Это дерьмо прям на крайний случай",
    initial: "X",
    loginSite: "grok.com",
  },
};

export function ProviderCard({
  provider,
  active,
  limited,
  loggedIn,
  busy,
  onLogin,
  onLogout,
  onImportSession,
}: ProviderCardProps): JSX.Element {
  const meta = PROVIDER_META[provider];
  // Gemini has no direct "Войти" — Google's automated-browser sign-in block
  // makes a from-scratch login there unreliable enough to have pulled that
  // button entirely (see provider-card__note below). Importing an
  // already-established session from the user's own real browser sidesteps
  // that block, so once that succeeds `loggedIn` is trustworthy here same
  // as any other provider.
  const canLoginDirectly = provider !== "gemini";

  return (
    <div
      className={`provider-card${active ? " provider-card--active" : ""}${
        limited ? " provider-card--limited" : ""
      }`}
    >
      <div className="provider-card__header">
        <span className="provider-card__logo" aria-hidden="true">
          {meta.initial}
        </span>
        <div className="provider-card__title">
          <span className="provider-card__name">{meta.label}</span>
          <span className={`provider-card__status${loggedIn ? " provider-card__status--authed" : ""}`}>
            {loggedIn ? "Авторизован" : "Гость"}
          </span>
        </div>
      </div>

      <p className="provider-card__description">{meta.description}</p>

      {limited && <p className="provider-card__limit">Дневной лимит исчерпан</p>}

      {!canLoginDirectly && !loggedIn && (
        // Login unreliable enough (Google's automated-browser sign-in block)
        // to have pulled the direct-login button rather than ship a broken
        // one — Gemini still works fine as a guest, or via the import
        // button below, just never via a from-scratch automated login.
        <p className="provider-card__note">Прямой вход недоступен — работает в гостевом режиме</p>
      )}

      <div className="provider-card__actions">
        {loggedIn ? (
          <button type="button" className="provider-card__auth-button" onClick={onLogout} disabled={busy}>
            {busy ? "…" : "Выйти"}
          </button>
        ) : (
          <>
            {canLoginDirectly && (
              <button type="button" className="provider-card__auth-button" onClick={onLogin} disabled={busy}>
                {busy ? "…" : "Войти"}
              </button>
            )}
            <button
              type="button"
              className="provider-card__auth-button provider-card__auth-button--secondary"
              onClick={onImportSession}
              disabled={busy}
            >
              {busy ? "…" : "Импорт из браузера"}
            </button>
          </>
        )}
      </div>

      {!loggedIn && (
        <p className="provider-card__note">
          Как это работает: войдите на {meta.loginSite} в своём обычном браузере (Firefox или Chrome), как обычно
          заходите на сайты, — затем нажмите «Импорт из браузера», и NABVE скопирует эту сессию себе.
        </p>
      )}
    </div>
  );
}
