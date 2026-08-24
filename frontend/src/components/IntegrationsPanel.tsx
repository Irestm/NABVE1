import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  SiBlender,
  SiBlenderHex,
  SiClaude,
  SiClaudeHex,
  SiFigma,
  SiFigmaHex,
  SiGithub,
  SiGooglegemini,
  SiGooglegeminiHex,
  SiSpotify,
  SiSpotifyHex,
  SiTelegram,
  SiTelegramHex,
  SiWordpress,
  SiWordpressHex,
  SiYoutube,
  SiYoutubeHex,
} from "@icons-pack/react-simple-icons";
import { Briefcase, Globe } from "lucide-react";
import {
  deleteClaudeApiKey,
  deleteGeminiApiKey,
  deleteGithubPat,
  deleteYoutubeApiKey,
  disconnectSpotify,
  getBlenderAddonDownloadUrl,
  getClaudeKeyStatus,
  getFigmaPluginDownloadUrl,
  getGeminiKeyStatus,
  getGithubPatStatus,
  getSpotifyStatus,
  getWordpressPluginDownloadUrl,
  getYoutubeStatus,
  saveClaudeApiKey,
  saveGeminiApiKey,
  saveGithubPat,
  saveSpotifyClientId,
  saveYoutubeApiKey,
  startSpotifyLogin,
} from "../api/client";
import { ApiKeyField } from "./ApiKeyField";
import { IntegrationTile } from "./IntegrationTile";
import { StatusPanel } from "./StatusPanel";
import { TelegramIntegrationPanel } from "./TelegramIntegrationPanel";
import type { ClaudeKeyStatus, GeminiKeyStatus, GithubStatus, SpotifyStatus, YouTubeStatus } from "../types";
import "./IntegrationTile.css";
import "./IntegrationsPanel.css";

// GitHub's own brand mark is near-black (#181717) — invisible against this
// app's dark background. A lighter gray keeps the tile actually visible
// without pretending it's the "real" brand color for anything else.
const GITHUB_TILE_COLOR = "#c9d1d9";

// No single brand mark covers Word+Excel+PowerPoint+Access+OneNote at once
// — a generic "office suite" blue instead of borrowing any one app's color.
const OFFICE_TILE_COLOR = "#2b7de9";

const OFFICE_GUIDE_STEPS = [
  "Нужен уже установленный LibreOffice (Linux) или Microsoft Office (Windows) — NABVE использует его напрямую, свой редактор не ставит и ничего скачивать не нужно.",
  "Word: скажите или напишите «Открой Word» либо «Создай документ».",
  "Excel: «Открой Excel» либо «Создай таблицу».",
  "PowerPoint: «Открой презентацию» либо «Создай PowerPoint».",
  "Access: «Открой базу данных <имя>».",
  "OneNote: «Открой блокнот <имя>».",
  "Дальше — голосом или текстом прямо в открытом документе: «напиши текст…», «вставь строку», «перейди на слайд 3» и т.д.",
];

const SPOTIFY_LOGIN_POLL_MS = 3000;
const SPOTIFY_LOGIN_POLL_MAX_ATTEMPTS = 40; // ~2 minutes

const YOUTUBE_API_KEY_GUIDE_STEPS = [
  "Откройте console.cloud.google.com и создайте проект (или выберите существующий).",
  "В разделе «APIs & Services» → «Library» найдите «YouTube Data API v3» и нажмите «Enable».",
  "В «APIs & Services» → «Credentials» нажмите «Create Credentials» → «API key».",
  "Скопируйте полученный ключ и вставьте его в поле ниже.",
];

const GEMINI_API_KEY_GUIDE_STEPS = [
  "Откройте aistudio.google.com и войдите с обычным Google-аккаунтом.",
  "Нажмите «Get API key» → «Create API key» (можно в новом или существующем проекте).",
  "Скопируйте ключ и вставьте его в поле ниже.",
];

const CLAUDE_API_KEY_GUIDE_STEPS = [
  "Откройте console.anthropic.com и зарегистрируйтесь (нужно подтвердить телефон).",
  "В разделе «API Keys» нажмите «Create Key».",
  "Пополните баланс — платно, но недорого при обычном использовании; минимум на пополнение стоит свериться прямо в консоли.",
  "Скопируйте ключ и вставьте его в поле ниже.",
];

const SPOTIFY_SETUP_GUIDE_STEPS = [
  "Откройте developer.spotify.com/dashboard и войдите со своим аккаунтом Spotify.",
  "Нажмите «Create app», укажите любое имя/описание.",
  "В Redirect URIs добавьте адрес ниже (скопируйте его целиком) и сохраните.",
  "Скопируйте Client ID со страницы приложения и вставьте его в поле ниже — Client Secret не нужен.",
];

const GITHUB_PAT_GUIDE_STEPS = [
  "Откройте github.com/settings/tokens и нажмите «Generate new token» (classic хватит).",
  "Для приватных репозиториев отметьте scope «repo»; для только публичных можно вообще без токена.",
  "Скопируйте токен (виден только один раз) и вставьте его в поле ниже.",
];

const TELEGRAM_GUIDE_STEPS = [
  "Получите свои api_id/api_hash на my.telegram.org/apps — бесплатно, один раз на всё приложение.",
  "Введите их в форму выше и нажмите «Сохранить».",
  "Нажмите «+ Добавить аккаунт», укажите метку и номер телефона в международном формате.",
  "Введите код, который придёт в само приложение Telegram.",
  "Если включена двухфакторная аутентификация — введите облачный пароль на последнем шаге.",
];

const AI_SESSIONS_GUIDE_STEPS = [
  "Ниже — список браузерных ИИ-провайдеров (Gemini/ChatGPT/DeepSeek/Grok).",
  "Нажмите «Войти» у нужного провайдера — откроется окно браузера с обычной страницей входа.",
  "Войдите в свой аккаунт как обычно и закройте окно — статус обновится на «подключено».",
  "Эта цепочка используется автоматически как бесплатный запасной вариант, когда не задан свой API-ключ.",
];

interface DownloadableIntegration {
  id: string;
  tagline: string;
  downloadUrl: string;
  downloadFilename: string;
  afterDownloadSteps: string[];
  manualSteps: string[];
}

// These three connect a *separate* app (WordPress, Figma Desktop, Blender)
// back to this Jarvis backend. The primary path is now "download the
// already-configured package and install it" (core/main.py's
// /api/integrations/*/*.zip, built by modules/integrations/packager.py,
// which bakes in this machine's address/token — nothing to type by hand);
// manualSteps is the old copy-the-folder-yourself path, kept only as a
// fallback for when the download button itself doesn't work. Source of
// truth for each: wordpress-plugin/jarvis-bridge.php's header comment,
// figma_plugin/README.md, blender_addon/__init__.py's docstring/bl_info —
// keep these in sync if those change.
const DOWNLOADABLE: Record<string, DownloadableIntegration> = {
  wordpress: {
    id: "wordpress",
    tagline: "Загружаете docx/PDF/картинку в админке — NABVE готовит из неё черновик поста",
    downloadUrl: getWordpressPluginDownloadUrl(),
    downloadFilename: "nabve-wordpress-plugin.zip",
    afterDownloadSteps: [
      "В админке сайта: Плагины → Добавить новый → Загрузить плагин → выберите скачанный файл → Установить → Активировать.",
      "В меню слева появится пункт «NABVE» — адрес и токен там уже подставлены, ничего вводить не нужно.",
      "Дальше можно загружать файлы — NABVE сам сделает черновик поста. Публикует его только человек, из обычного редактора WordPress.",
    ],
    manualSteps: [
      "Скопируйте папку wordpress-plugin в wp-content/plugins/ вашего сайта на WordPress.",
      "В админке: Плагины → найдите «NABVE Bridge» → Активировать.",
      "В меню слева откройте «NABVE» и укажите вручную: адрес backend NABVE (например http://<IP этого компьютера в локальной сети>:8756) и API-токен из файла data/api_token.txt в папке проекта.",
    ],
  },
  figma: {
    id: "figma",
    tagline: "Голосовые команды рисуют/двигают/красят слои прямо в открытом документе",
    downloadUrl: getFigmaPluginDownloadUrl(),
    downloadFilename: "nabve-figma-plugin.zip",
    afterDownloadSteps: [
      "Распакуйте скачанный архив в любую папку.",
      "В Figma Desktop: Plugins → Development → Import plugin from manifest… → выберите manifest.json из распакованной папки.",
      "Раз за сессию запускайте: Plugins → Development → NABVE Voice Control — токен уже вписан, дальше плагин работает в фоне, пока открыта Figma.",
    ],
    manualSteps: [
      "В папке figma_plugin выполните: npm install, затем npm run build.",
      "Откройте ui.html в текстовом редакторе и впишите в WS_TOKEN значение из файла data/api_token.txt.",
      "В Figma Desktop: Plugins → Development → Import plugin from manifest… → выберите manifest.json из этой же папки.",
    ],
  },
  blender: {
    id: "blender",
    tagline: "Голосом — объекты, модификаторы, материалы, рендер",
    downloadUrl: getBlenderAddonDownloadUrl(),
    downloadFilename: "nabve-blender-addon.zip",
    afterDownloadSteps: [
      "В Blender: Edit → Preferences → Add-ons → Install… → выберите скачанный .zip.",
      "Включите галочку у аддона «NABVE Voice Control» в списке.",
      "Больше ничего настраивать не нужно — свой локальный сервер аддон поднимает сам и начинает слушать команды сразу после включения.",
    ],
    manualSteps: [
      "В Blender: Edit → Preferences → Add-ons → Install… → укажите папку blender_addon (или сначала заархивируйте её в .zip сами).",
      "Включите галочку у аддона «NABVE Voice Control» в списке.",
    ],
  },
};

function InstructionToggle({ steps }: { steps: string[] }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="api-key-field__toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Скрыть инструкцию" : "Инструкция"}
      </button>
      {open && (
        <ol className="api-key-field__steps">
          {steps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      )}
    </>
  );
}

function DownloadableDetail({ integration }: { integration: DownloadableIntegration }): JSX.Element {
  const [afterOpen, setAfterOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  return (
    <>
      <p className="status-detail">{integration.tagline}</p>
      <div className="row">
        <a className="integration-detail__download" href={integration.downloadUrl} download={integration.downloadFilename}>
          Скачать
        </a>
      </div>
      <button type="button" className="api-key-field__toggle" onClick={() => setAfterOpen((v) => !v)}>
        {afterOpen ? "Скрыть инструкцию" : "Инструкция"}
      </button>
      {afterOpen && (
        <ol className="api-key-field__steps">
          {integration.afterDownloadSteps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      )}
      <button
        type="button"
        className="api-key-field__toggle api-key-field__toggle--secondary"
        onClick={() => setManualOpen((v) => !v)}
      >
        {manualOpen ? "Скрыть" : "Кнопка не сработала — установить вручную"}
      </button>
      {manualOpen && (
        <ol className="api-key-field__steps">
          {integration.manualSteps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      )}
    </>
  );
}

export function IntegrationsPanel(): JSX.Element {
  const [openId, setOpenId] = useState<string | null>(null);

  const [youtubeStatus, setYoutubeStatus] = useState<YouTubeStatus | null>(null);
  const [youtubeError, setYoutubeError] = useState("");

  const [geminiStatus, setGeminiStatus] = useState<GeminiKeyStatus | null>(null);
  const [geminiError, setGeminiError] = useState("");

  const [claudeKeyStatus, setClaudeKeyStatus] = useState<ClaudeKeyStatus | null>(null);
  const [claudeKeyError, setClaudeKeyError] = useState("");

  const [spotifyStatus, setSpotifyStatus] = useState<SpotifyStatus | null>(null);
  const [spotifyError, setSpotifyError] = useState("");
  const [spotifyClientIdInput, setSpotifyClientIdInput] = useState("");
  const [spotifyLoggingIn, setSpotifyLoggingIn] = useState(false);
  const [spotifySetupOpen, setSpotifySetupOpen] = useState(false);
  const spotifyPollTimeout = useRef<number | null>(null);

  const [githubStatus, setGithubStatus] = useState<GithubStatus | null>(null);
  const [githubError, setGithubError] = useState("");

  useEffect(() => {
    getYoutubeStatus()
      .then(setYoutubeStatus)
      .catch((error) => {
        console.error("Failed to load YouTube integration status:", error);
        setYoutubeError("Не удалось загрузить статус интеграции с YouTube.");
      });
  }, []);

  useEffect(() => {
    getGeminiKeyStatus()
      .then(setGeminiStatus)
      .catch((error) => {
        console.error("Failed to load Gemini key status:", error);
        setGeminiError("Не удалось загрузить статус ключа Gemini.");
      });
  }, []);

  useEffect(() => {
    getClaudeKeyStatus()
      .then(setClaudeKeyStatus)
      .catch((error) => {
        console.error("Failed to load Claude key status:", error);
        setClaudeKeyError("Не удалось загрузить статус ключа Claude.");
      });
  }, []);

  useEffect(() => {
    getSpotifyStatus()
      .then(setSpotifyStatus)
      .catch((error) => {
        console.error("Failed to load Spotify status:", error);
        setSpotifyError("Не удалось загрузить статус Spotify.");
      });
  }, []);

  useEffect(() => {
    getGithubPatStatus()
      .then(setGithubStatus)
      .catch((error) => {
        console.error("Failed to load GitHub status:", error);
        setGithubError("Не удалось загрузить статус GitHub.");
      });
  }, []);

  useEffect(() => {
    return () => {
      if (spotifyPollTimeout.current !== null) {
        window.clearTimeout(spotifyPollTimeout.current);
      }
    };
  }, []);

  function pollSpotifyStatusUntilConnected(attempt = 0): void {
    if (attempt >= SPOTIFY_LOGIN_POLL_MAX_ATTEMPTS) {
      setSpotifyLoggingIn(false);
      return;
    }
    spotifyPollTimeout.current = window.setTimeout(() => {
      getSpotifyStatus()
        .then((status) => {
          setSpotifyStatus(status);
          if (status.connected) {
            setSpotifyLoggingIn(false);
          } else {
            pollSpotifyStatusUntilConnected(attempt + 1);
          }
        })
        .catch(() => pollSpotifyStatusUntilConnected(attempt + 1));
    }, SPOTIFY_LOGIN_POLL_MS);
  }

  async function handleSpotifyLogin(): Promise<void> {
    setSpotifyLoggingIn(true);
    setSpotifyError("");
    try {
      const authorizeUrl = await startSpotifyLogin();
      window.open(authorizeUrl, "_blank", "noopener,noreferrer");
      pollSpotifyStatusUntilConnected();
    } catch (error) {
      console.error("Failed to start Spotify login:", error);
      setSpotifyError("Не удалось начать вход в Spotify.");
      setSpotifyLoggingIn(false);
    }
  }

  async function handleSaveSpotifyClientId(): Promise<void> {
    const trimmed = spotifyClientIdInput.trim();
    if (!trimmed) {
      return;
    }
    setSpotifyError("");
    try {
      setSpotifyStatus(await saveSpotifyClientId(trimmed));
      setSpotifyClientIdInput("");
    } catch (error) {
      console.error("Failed to save the Spotify Client ID:", error);
      setSpotifyError("Не удалось сохранить Client ID.");
    }
  }

  async function handleSpotifyDisconnect(): Promise<void> {
    setSpotifyError("");
    try {
      setSpotifyStatus(await disconnectSpotify());
    } catch (error) {
      console.error("Failed to disconnect Spotify:", error);
      setSpotifyError("Не удалось отключить Spotify.");
    }
  }

  function toggle(id: string): void {
    setOpenId((current) => (current === id ? null : id));
  }

  const TILES: { id: string; name: string; icon: JSX.Element; color: string }[] = [
    { id: "wordpress", name: "WordPress", icon: <SiWordpress size={20} color={SiWordpressHex} />, color: SiWordpressHex },
    { id: "figma", name: "Figma", icon: <SiFigma size={20} color={SiFigmaHex} />, color: SiFigmaHex },
    { id: "blender", name: "Blender", icon: <SiBlender size={20} color={SiBlenderHex} />, color: SiBlenderHex },
    { id: "youtube", name: "YouTube", icon: <SiYoutube size={20} color={SiYoutubeHex} />, color: SiYoutubeHex },
    { id: "gemini", name: "Gemini", icon: <SiGooglegemini size={20} color={SiGooglegeminiHex} />, color: SiGooglegeminiHex },
    { id: "claude", name: "Claude", icon: <SiClaude size={20} color={SiClaudeHex} />, color: SiClaudeHex },
    { id: "spotify", name: "Spotify", icon: <SiSpotify size={20} color={SiSpotifyHex} />, color: SiSpotifyHex },
    { id: "github", name: "GitHub", icon: <SiGithub size={20} color={GITHUB_TILE_COLOR} />, color: GITHUB_TILE_COLOR },
    { id: "telegram", name: "Telegram", icon: <SiTelegram size={20} color={SiTelegramHex} />, color: SiTelegramHex },
    { id: "ai_sessions", name: "ИИ через браузер", icon: <Globe size={20} />, color: "var(--accent-blue)" },
    { id: "office", name: "Офисный пакет", icon: <Briefcase size={20} color={OFFICE_TILE_COLOR} />, color: OFFICE_TILE_COLOR },
  ];

  const openTile = TILES.find((tile) => tile.id === openId) ?? null;

  return (
    <div className="section integrations-panel">
      <h3>Интеграции</h3>
      <p className="status-detail">Нажмите на плитку, чтобы подключить или настроить.</p>

      <div className="integration-tile-grid">
        {TILES.map((tile) => (
          <IntegrationTile
            key={tile.id}
            name={tile.name}
            icon={tile.icon}
            brandColor={tile.color}
            active={openId === tile.id}
            onClick={() => toggle(tile.id)}
          />
        ))}
      </div>

      <div
        className={`integration-detail${openTile ? " integration-detail--open" : ""}`}
        style={openTile ? ({ "--brand-color": openTile.color } as CSSProperties) : undefined}
      >
        <div className="integration-detail__inner">
          {openTile && (
            <>
              <p className="integration-detail__title">
                {openTile.icon}
                {openTile.name}
              </p>

              {openTile.id in DOWNLOADABLE && <DownloadableDetail integration={DOWNLOADABLE[openTile.id]} />}

              {openTile.id === "youtube" && (
                <>
                  <p className="status-detail">
                    Поиск и управление видео: через браузер — работает из коробки, ничего не нужно вводить. Свой
                    ключ — необязательный апгрейд: бесплатно, но не безлимитно (~100 поисков в день).
                  </p>
                  {youtubeError && <p className="status-error">{youtubeError}</p>}
                  {youtubeStatus && (
                    <ApiKeyField
                      label="Свой YouTube API-ключ"
                      configured={youtubeStatus.key_configured}
                      configuredText={`Ключ активен — использовано ${youtubeStatus.units_used} из ${youtubeStatus.daily_limit} units сегодня.`}
                      notConfiguredText="Ключ не задан — используется браузер."
                      guideTitle="Как получить бесплатный ключ"
                      guideSteps={YOUTUBE_API_KEY_GUIDE_STEPS}
                      onSave={async (apiKey) => setYoutubeStatus(await saveYoutubeApiKey(apiKey))}
                      onDelete={async () => setYoutubeStatus(await deleteYoutubeApiKey())}
                    />
                  )}
                </>
              )}

              {openTile.id === "gemini" && (
                <>
                  <p className="status-detail">
                    Бесплатно (с лимитом, ассистент сам подстрахуется и переключится на локальную модель/браузер,
                    если лимит близко). Ускоряет голосовой чат и распознавание команд.
                  </p>
                  {geminiError && <p className="status-error">{geminiError}</p>}
                  {geminiStatus && (
                    <ApiKeyField
                      label="Gemini API-ключ (бесплатно)"
                      configured={geminiStatus.key_configured}
                      configuredText={`Ключ активен — использовано ${geminiStatus.requests_used_today} из ${geminiStatus.daily_limit} запросов сегодня.`}
                      notConfiguredText="Ключ не задан — используется локальная модель/браузер."
                      guideTitle="Как получить бесплатный ключ"
                      guideSteps={GEMINI_API_KEY_GUIDE_STEPS}
                      onSave={async (apiKey) => setGeminiStatus(await saveGeminiApiKey(apiKey))}
                      onDelete={async () => setGeminiStatus(await deleteGeminiApiKey())}
                    />
                  )}
                </>
              )}

              {openTile.id === "claude" && (
                <>
                  <p className="status-detail">
                    Платно (реалистично: единицы долларов в месяц при обычном использовании одним человеком), зато
                    заметно надёжнее и качественнее на сложных запросах.
                  </p>
                  {claudeKeyError && <p className="status-error">{claudeKeyError}</p>}
                  {claudeKeyStatus && (
                    <ApiKeyField
                      label="Claude (Anthropic) API-ключ"
                      configured={claudeKeyStatus.key_configured}
                      configuredText="Ключ активен — используется для сложных запросов."
                      notConfiguredText="Ключ не задан — используется браузерная цепочка (Gemini/ChatGPT/DeepSeek/Grok)."
                      guideTitle="Как получить ключ и сколько это стоит"
                      guideSteps={CLAUDE_API_KEY_GUIDE_STEPS}
                      onSave={async (apiKey) => setClaudeKeyStatus(await saveClaudeApiKey(apiKey))}
                      onDelete={async () => setClaudeKeyStatus(await deleteClaudeApiKey())}
                    />
                  )}
                </>
              )}

              {openTile.id === "spotify" && (
                <>
                  <p className="status-detail">
                    Официальный API Spotify + вход через браузер. Нужен бесплатный Client ID из своего приложения в
                    Spotify — Client Secret не требуется.
                  </p>
                  {spotifyError && <p className="status-error">{spotifyError}</p>}
                  {spotifyStatus && (
                    <>
                      <p className={spotifyStatus.connected ? "api-key-field__success" : "status-detail"}>
                        {spotifyStatus.connected
                          ? "Spotify подключён."
                          : spotifyStatus.client_id_configured
                            ? "Client ID задан — осталось войти."
                            : "Не настроено."}
                      </p>
                      {!spotifyStatus.client_id_configured && (
                        <div className="row">
                          <input
                            type="text"
                            value={spotifyClientIdInput}
                            onChange={(event) => setSpotifyClientIdInput(event.target.value)}
                            placeholder="Spotify Client ID"
                          />
                          <button
                            type="button"
                            onClick={() => void handleSaveSpotifyClientId()}
                            disabled={!spotifyClientIdInput.trim()}
                          >
                            Сохранить
                          </button>
                        </div>
                      )}
                      {spotifyStatus.client_id_configured && !spotifyStatus.connected && (
                        <div className="row">
                          <button type="button" onClick={() => void handleSpotifyLogin()} disabled={spotifyLoggingIn}>
                            {spotifyLoggingIn ? "Ожидаю вход в браузере…" : "Войти в Spotify"}
                          </button>
                        </div>
                      )}
                      {spotifyStatus.client_id_configured && (
                        <div className="row">
                          <button type="button" onClick={() => void handleSpotifyDisconnect()}>
                            {spotifyStatus.connected ? "Отключить" : "Сбросить Client ID"}
                          </button>
                        </div>
                      )}
                      <button
                        type="button"
                        className="api-key-field__toggle"
                        onClick={() => setSpotifySetupOpen((open) => !open)}
                      >
                        {spotifySetupOpen ? "Скрыть инструкцию" : "Как получить Client ID"}
                      </button>
                      {spotifySetupOpen && (
                        <ol className="api-key-field__steps">
                          <li>{SPOTIFY_SETUP_GUIDE_STEPS[0]}</li>
                          <li>{SPOTIFY_SETUP_GUIDE_STEPS[1]}</li>
                          <li>
                            {SPOTIFY_SETUP_GUIDE_STEPS[2]}
                            <br />
                            <code>{spotifyStatus.redirect_uri}</code>
                          </li>
                          <li>{SPOTIFY_SETUP_GUIDE_STEPS[3]}</li>
                        </ol>
                      )}
                    </>
                  )}
                </>
              )}

              {openTile.id === "github" && (
                <>
                  {githubError && <p className="status-error">{githubError}</p>}
                  {githubStatus && (
                    <ApiKeyField
                      label="GitHub Personal Access Token"
                      configured={githubStatus.pat_configured}
                      helperText="Нужен только для анализа файлов из приватных репозиториев — публичные и так доступны без токена."
                      configuredText="Токен активен."
                      notConfiguredText="Токен не задан — публичные репозитории всё равно доступны."
                      guideTitle="Как получить токен"
                      guideSteps={GITHUB_PAT_GUIDE_STEPS}
                      onSave={async (pat) => setGithubStatus(await saveGithubPat(pat))}
                      onDelete={async () => setGithubStatus(await deleteGithubPat())}
                    />
                  )}
                </>
              )}

              {openTile.id === "telegram" && (
                <>
                  <TelegramIntegrationPanel />
                  <InstructionToggle steps={TELEGRAM_GUIDE_STEPS} />
                </>
              )}

              {openTile.id === "ai_sessions" && (
                <>
                  <p className="status-detail">
                    Браузерная цепочка ИИ-провайдеров (Gemini/ChatGPT/DeepSeek/Grok) — фоллбэк, когда нет своего
                    API-ключа. Здесь можно войти в аккаунт или импортировать уже открытую сессию браузера.
                  </p>
                  <StatusPanel />
                  <InstructionToggle steps={AI_SESSIONS_GUIDE_STEPS} />
                </>
              )}

              {openTile.id === "office" && (
                <>
                  <p className="status-detail">
                    Word, Excel, PowerPoint, Access, OneNote — голосом или текстом, без API-ключей и без скачивания:
                    NABVE управляет уже установленным на этом компьютере офисным пакетом напрямую.
                  </p>
                  <InstructionToggle steps={OFFICE_GUIDE_STEPS} />
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
