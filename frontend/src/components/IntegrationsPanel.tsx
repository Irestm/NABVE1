import { useState } from "react";
import { getBlenderAddonDownloadUrl, getFigmaPluginDownloadUrl, getWordpressPluginDownloadUrl } from "../api/client";
import "./IntegrationsPanel.css";

interface IntegrationInfo {
  id: string;
  name: string;
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
const INTEGRATIONS: IntegrationInfo[] = [
  {
    id: "wordpress",
    name: "WordPress",
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
  {
    id: "figma",
    name: "Figma",
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
  {
    id: "blender",
    name: "Blender",
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
];

export function IntegrationsPanel(): JSX.Element {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [manualId, setManualId] = useState<string | null>(null);

  return (
    <div className="section integrations-panel">
      <h3>Интеграции</h3>
      <p className="status-detail">
        Скачайте готовый файл для нужной программы — адрес и токен NABVE уже вписаны внутрь, вводить вручную ничего
        не нужно.
      </p>

      {INTEGRATIONS.map((integration) => {
        const expanded = expandedId === integration.id;
        const manualExpanded = manualId === integration.id;
        return (
          <div key={integration.id} className="integrations-panel__card">
            <div className="integrations-panel__card-header">
              <span className="integrations-panel__card-name">{integration.name}</span>
              <a
                className="integrations-panel__download"
                href={integration.downloadUrl}
                download={integration.downloadFilename}
              >
                Скачать
              </a>
            </div>
            <p className="integrations-panel__card-tagline">{integration.tagline}</p>
            <button
              type="button"
              className="integrations-panel__toggle"
              onClick={() => setExpandedId(expanded ? null : integration.id)}
            >
              {expanded ? "Скрыть шаги после скачивания" : "Что делать после скачивания"}
            </button>
            {expanded && (
              <ol className="integrations-panel__steps">
                {integration.afterDownloadSteps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            )}
            <button
              type="button"
              className="integrations-panel__toggle integrations-panel__toggle--secondary"
              onClick={() => setManualId(manualExpanded ? null : integration.id)}
            >
              {manualExpanded ? "Скрыть" : "Кнопка не сработала — установить вручную"}
            </button>
            {manualExpanded && (
              <ol className="integrations-panel__steps">
                {integration.manualSteps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            )}
          </div>
        );
      })}
    </div>
  );
}
