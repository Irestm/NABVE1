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
}

interface ProviderMeta {
  label: string;
  description: string;
  initial: string;
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
  },
  chatgpt: {
    label: "ChatGPT",
    description: "Сильный в рассуждениях и написании текста, второй по приоритету",
    initial: "C",
  },
  deepseek: {
    label: "DeepSeek",
    description: "Хорош в коде и технических задачах, запасной вариант",
    initial: "D",
  },
  grok: {
    label: "Grok",
    description: "Это дерьмо прям на крайний случай",
    initial: "X",
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
}: ProviderCardProps): JSX.Element {
  const meta = PROVIDER_META[provider];

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

      <button
        type="button"
        className="provider-card__auth-button"
        onClick={loggedIn ? onLogout : onLogin}
        disabled={busy}
      >
        {busy ? "…" : loggedIn ? "Выйти" : "Войти"}
      </button>
    </div>
  );
}
