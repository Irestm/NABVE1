import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, RefreshCw, TriangleAlert } from "lucide-react";
import {
  deleteProviderKey,
  getProviders,
  getProvidersHealth,
  saveProviderKey,
  updateProvidersConfig,
} from "../api/providers";
import type {
  ChainKind,
  ClaudeConnection,
  ProviderHealth,
  ProviderHealthStatus,
  ProviderInfo,
  ProvidersOverview,
} from "../api/providers";
import { ApiKeyField } from "./ApiKeyField";
import "./ProvidersPanel.css";

interface ProviderMeta {
  title: string;
  description: string;
  guideSteps?: string[];
}

const PROVIDER_META: Record<string, ProviderMeta> = {
  ollama: {
    title: "Локальная модель (Ollama)",
    description: "Бесплатно и офлайн, на вашей видеокарте. Ключ не нужен — Ollama ставится автоустановщиком.",
  },
  anthropic_api: {
    title: "Claude — API-ключ",
    description: "Оплата по использованию через console.anthropic.com. Сильнее всего на сложных запросах.",
    guideSteps: [
      "Откройте console.anthropic.com и зарегистрируйтесь (нужно подтвердить телефон).",
      "В разделе «API Keys» нажмите «Create Key».",
      "Пополните баланс — платно, но недорого при обычном использовании; минимум на пополнение смотрите в консоли.",
      "Скопируйте ключ и вставьте его в поле ниже.",
    ],
  },
  anthropic_subscription: {
    title: "Claude — подписка",
    description: "Через ваш собственный установленный Claude CLI, под вашим аккаунтом. NABVE не хранит и не читает ваши данные входа.",
  },
  openai_api: {
    title: "OpenAI API",
    description: "Модели OpenAI по вашему ключу, оплата по использованию.",
    guideSteps: [
      "Откройте platform.openai.com и войдите.",
      "В разделе «API keys» нажмите «Create new secret key».",
      "Пополните баланс в «Billing» и вставьте ключ в поле ниже.",
    ],
  },
  gemini_api: {
    title: "Gemini API",
    description: "Бесплатный тариф с лимитом — ассистент сам переключится дальше по цепочке, когда лимит близко.",
    guideSteps: [
      "Откройте aistudio.google.com и войдите с обычным Google-аккаунтом.",
      "Нажмите «Get API key» → «Create API key».",
      "Скопируйте ключ и вставьте его в поле ниже.",
    ],
  },
  deepseek_api: {
    title: "DeepSeek API",
    description: "Недорогой облачный вариант по вашему ключу.",
    guideSteps: [
      "Откройте platform.deepseek.com и зарегистрируйтесь.",
      "В разделе «API keys» создайте ключ и пополните баланс.",
      "Вставьте ключ в поле ниже.",
    ],
  },
  groq_api: {
    title: "Groq API",
    description: "Очень быстрый бесплатный тариф с поминутным лимитом.",
    guideSteps: [
      "Откройте console.groq.com и войдите.",
      "В разделе «API Keys» нажмите «Create API Key».",
      "Вставьте ключ в поле ниже.",
    ],
  },
  browser_chain: {
    title: "ИИ через браузер",
    description: "Вход в аккаунты этих сервисов — на вкладке «Интеграции», плитка «ИИ через браузер».",
  },
};

const STATUS_LABELS: Record<ProviderHealthStatus, string> = {
  ok: "работает",
  not_configured: "нет ключа",
  disabled: "выключен",
  auth_error: "ключ отклонён",
  rate_limited: "лимит",
  unavailable: "недоступен",
};

const CHAIN_LABELS: Record<ChainKind, string> = {
  default: "Обычные запросы",
  complex: "Сложные запросы (свежие данные, поиск)",
};

const CLAUDE_PROVIDERS = new Set(["anthropic_api", "anthropic_subscription"]);
const CLAUDE_CLI_SETUP_URL = "https://code.claude.com/docs/en/setup";
const ANTHROPIC_USAGE_POLICY_URL = "https://www.anthropic.com/legal/aup";

function titleOf(name: string): string {
  return PROVIDER_META[name]?.title ?? name;
}

function moveItem(items: string[], index: number, offset: number): string[] {
  const target = index + offset;
  if (target < 0 || target >= items.length) {
    return items;
  }
  const next = [...items];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

interface StatusBadgeProps {
  health: ProviderHealth | undefined;
  checking: boolean;
}

function StatusBadge({ health, checking }: StatusBadgeProps): JSX.Element {
  if (!health) {
    return <span className="providers__badge providers__badge--pending">{checking ? "проверка…" : "—"}</span>;
  }
  const latency = health.status === "ok" && health.latency_ms !== null ? ` · ${health.latency_ms} мс` : "";
  return (
    <span className={`providers__badge providers__badge--${health.status}`} title={health.detail ?? undefined}>
      {STATUS_LABELS[health.status]}
      {latency}
    </span>
  );
}

interface ProviderRowProps {
  provider: ProviderInfo;
  health: ProviderHealth | undefined;
  checking: boolean;
  warning: string;
  onToggle: (enabled: boolean) => Promise<void>;
  onSaveKey: (apiKey: string) => Promise<void>;
  onDeleteKey: () => Promise<void>;
}

function ProviderRow({
  provider,
  health,
  checking,
  warning,
  onToggle,
  onSaveKey,
  onDeleteKey,
}: ProviderRowProps): JSX.Element {
  const meta = PROVIDER_META[provider.name];
  const [busy, setBusy] = useState(false);

  async function handleToggle(): Promise<void> {
    setBusy(true);
    try {
      await onToggle(!provider.enabled);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`providers__row${provider.enabled ? "" : " providers__row--off"}`}>
      <div className="providers__row-head">
        <div className="providers__row-title">
          <span className="providers__name">{titleOf(provider.name)}</span>
          {provider.model && <span className="providers__model">{provider.model}</span>}
        </div>
        <StatusBadge health={health} checking={checking} />
        <label className="providers__switch" title={provider.enabled ? "Выключить" : "Включить"}>
          <input type="checkbox" checked={provider.enabled} disabled={busy} onChange={() => void handleToggle()} />
          <span className="providers__switch-track" aria-hidden="true" />
          <span className="visually-hidden">{provider.enabled ? "Выключить" : "Включить"}</span>
        </label>
      </div>
      {meta && <p className="status-detail">{meta.description}</p>}
      {provider.experimental && (
        <p className="providers__warning">
          <TriangleAlert size={16} aria-hidden="true" />
          {warning}
        </p>
      )}
      {provider.needs_key && (
        <ApiKeyField
          label="API-ключ"
          configured={provider.key_configured}
          configuredText="Ключ сохранён в системном хранилище секретов."
          notConfiguredText="Ключ не задан — провайдер пропускается в цепочке."
          guideTitle="Где взять ключ"
          guideSteps={meta?.guideSteps ?? []}
          onSave={onSaveKey}
          onDelete={onDeleteKey}
        />
      )}
    </li>
  );
}

interface ChainEditorProps {
  kind: ChainKind;
  names: string[];
  providers: Map<string, ProviderInfo>;
  onChange: (names: string[]) => Promise<void>;
}

function ChainEditor({ kind, names, providers, onChange }: ChainEditorProps): JSX.Element {
  const [busy, setBusy] = useState(false);

  async function move(index: number, offset: number): Promise<void> {
    setBusy(true);
    try {
      await onChange(moveItem(names, index, offset));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="providers__chain">
      <span className="providers__chain-title">{CHAIN_LABELS[kind]}</span>
      <ol className="providers__chain-list">
        {names.map((name, index) => {
          const info = providers.get(name);
          const inactive = !info || !info.enabled || (info.needs_key && !info.key_configured);
          return (
            <li key={name} className={`providers__chain-item${inactive ? " providers__chain-item--inactive" : ""}`}>
              <span className="providers__chain-index">{index + 1}</span>
              <span className="providers__chain-name">{titleOf(name)}</span>
              <button
                type="button"
                className="providers__icon-button"
                onClick={() => void move(index, -1)}
                disabled={busy || index === 0}
                aria-label={`Поднять «${titleOf(name)}» выше`}
              >
                <ArrowUp size={16} />
              </button>
              <button
                type="button"
                className="providers__icon-button"
                onClick={() => void move(index, 1)}
                disabled={busy || index === names.length - 1}
                aria-label={`Опустить «${titleOf(name)}» ниже`}
              >
                <ArrowDown size={16} />
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ProvidersPanel(): JSX.Element {
  const [overview, setOverview] = useState<ProvidersOverview | null>(null);
  const [health, setHealth] = useState<Map<string, ProviderHealth>>(new Map());
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  const refreshHealth = useCallback(async (): Promise<void> => {
    setChecking(true);
    try {
      const results = await getProvidersHealth();
      setHealth(new Map(results.map((item) => [item.name, item])));
    } catch (err) {
      console.error("Failed to check AI provider health:", err);
      setError("Не удалось проверить провайдеров.");
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    getProviders()
      .then(setOverview)
      .catch((err) => {
        console.error("Failed to load AI providers:", err);
        setError("Не удалось загрузить список провайдеров.");
      });
    void refreshHealth();
  }, [refreshHealth]);

  const providersByName = useMemo(
    () => new Map((overview?.providers ?? []).map((provider) => [provider.name, provider])),
    [overview],
  );

  async function apply(change: Promise<ProvidersOverview>, recheck: boolean): Promise<void> {
    setError("");
    try {
      setOverview(await change);
      if (recheck) {
        void refreshHealth();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить изменения.");
      throw err;
    }
  }

  async function setConnection(connection: ClaudeConnection): Promise<void> {
    await apply(updateProvidersConfig({ claude_connection: connection }), false).catch(() => undefined);
  }

  if (!overview) {
    return (
      <div className="section providers">
        <h3>Провайдеры ИИ</h3>
        {error ? <p className="status-error">{error}</p> : <p className="status-detail">Загрузка…</p>}
      </div>
    );
  }

  const claudeApi = providersByName.get("anthropic_api");
  const otherProviders = overview.providers.filter((provider) => !CLAUDE_PROVIDERS.has(provider.name));

  return (
    <div className="section providers">
      <div className="providers__header">
        <div>
          <h3>Провайдеры ИИ</h3>
          <p className="status-detail">
            Ассистент идёт по цепочке сверху вниз и переключается на следующего, если провайдер недоступен, упёрся в
            лимит или отклонил ключ.
          </p>
        </div>
        <button type="button" className="providers__refresh" onClick={() => void refreshHealth()} disabled={checking}>
          <RefreshCw size={16} className={checking ? "providers__spin" : undefined} />
          Проверить
        </button>
      </div>

      {error && <p className="status-error">{error}</p>}

      <section className="providers__claude" aria-label="Claude">
        <div className="providers__claude-head">
          <span className="providers__claude-title">Claude</span>
          <StatusBadge
            health={health.get(overview.claude_connection === "api_key" ? "anthropic_api" : "anthropic_subscription")}
            checking={checking}
          />
        </div>
        <div className="providers__segmented" role="radiogroup" aria-label="Способ подключения Claude">
          <button
            type="button"
            role="radio"
            aria-checked={overview.claude_connection === "subscription"}
            className={overview.claude_connection === "subscription" ? "providers__segment--active" : undefined}
            disabled={!overview.subscription_available}
            onClick={() => void setConnection("subscription")}
          >
            Подписка (через свой Claude CLI)
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={overview.claude_connection === "api_key"}
            className={overview.claude_connection === "api_key" ? "providers__segment--active" : undefined}
            onClick={() => void setConnection("api_key")}
          >
            API-ключ
          </button>
        </div>
        {!overview.subscription_available && (
          <p className="status-detail">Подключение через подписку недоступно в этой сборке.</p>
        )}
        {overview.claude_connection === "subscription" && overview.subscription_available && (
          <div className="providers__subscription">
            <p className="status-detail">{PROVIDER_META.anthropic_subscription?.description}</p>
            <ol className="providers__steps">
              <li>
                Установите Claude CLI по официальной инструкции:{" "}
                <a href={CLAUDE_CLI_SETUP_URL} target="_blank" rel="noreferrer">
                  {CLAUDE_CLI_SETUP_URL}
                </a>{" "}
                (Linux/macOS: <code>curl -fsSL https://claude.ai/install.sh | bash</code>).
              </li>
              <li>
                В терминале выполните <code>claude</code> и войдите своим аккаунтом Claude — вход происходит только в
                CLI, NABVE не видит и не хранит ваши данные входа.
              </li>
              <li>Нажмите «Проверить» — статус должен стать «работает».</li>
            </ol>
          </div>
        )}
        <p className="status-detail providers__terms">
          Только некоммерческое использование. Нельзя применять Claude для действий, нарушающих закон, — см.{" "}
          <a href={ANTHROPIC_USAGE_POLICY_URL} target="_blank" rel="noreferrer">
            Usage Policy Anthropic
          </a>
          .
        </p>
        {overview.claude_connection === "api_key" && claudeApi && (
          <ProviderRow
            provider={claudeApi}
            health={health.get("anthropic_api")}
            checking={checking}
            warning={overview.experimental_warning}
            onToggle={(enabled) => apply(updateProvidersConfig({ enabled: { anthropic_api: enabled } }), true)}
            onSaveKey={(apiKey) => apply(saveProviderKey("anthropic_api", apiKey), true)}
            onDeleteKey={() => apply(deleteProviderKey("anthropic_api"), true)}
          />
        )}
      </section>

      <ul className="providers__list">
        {otherProviders.map((provider) => (
          <ProviderRow
            key={provider.name}
            provider={provider}
            health={health.get(provider.name)}
            checking={checking}
            warning={overview.experimental_warning}
            onToggle={(enabled) => apply(updateProvidersConfig({ enabled: { [provider.name]: enabled } }), true)}
            onSaveKey={(apiKey) => apply(saveProviderKey(provider.name, apiKey), true)}
            onDeleteKey={() => apply(deleteProviderKey(provider.name), true)}
          />
        ))}
      </ul>

      <div className="providers__chains">
        {(Object.keys(CHAIN_LABELS) as ChainKind[]).map((kind) => (
          <ChainEditor
            key={kind}
            kind={kind}
            names={overview.chains[kind] ?? []}
            providers={providersByName}
            onChange={(names) => apply(updateProvidersConfig({ chains: { [kind]: names } }), false)}
          />
        ))}
      </div>
    </div>
  );
}
