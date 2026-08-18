/* global jarvisBridgeConfig */
(function () {
  "use strict";

  var form = document.getElementById("jarvis-upload-form");
  if (!form) {
    return;
  }
  var statusEl = document.getElementById("jarvis-upload-status");
  var POLL_INTERVAL_MS = 2000;
  var POLL_MAX_ATTEMPTS = 150; // 5 minutes

  function setStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.style.color = isError ? "#b32d2e" : "";
  }

  function pollJob(jobId, attempt) {
    if (attempt >= POLL_MAX_ATTEMPTS) {
      setStatus("NABVE не ответил вовремя — проверьте вкладку с браузером NABVE.", true);
      return;
    }
    fetch(jarvisBridgeConfig.backendUrl + "/api/wordpress/upload/" + jobId, {
      headers: { "X-Assistant-Token": jarvisBridgeConfig.apiToken },
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (job) {
        if (job.status === "draft_ready") {
          setStatus(job.message || "Черновик готов!", false);
        } else if (job.status === "failed") {
          setStatus(job.message || "Не удалось подготовить черновик.", true);
        } else {
          setStatus("NABVE готовит черновик… (" + job.status + ")", false);
          window.setTimeout(function () {
            pollJob(jobId, attempt + 1);
          }, POLL_INTERVAL_MS);
        }
      })
      .catch(function (pollError) {
        console.error("Jarvis upload status poll failed, retrying:", pollError);
        window.setTimeout(function () {
          pollJob(jobId, attempt + 1);
        }, POLL_INTERVAL_MS);
      });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();

    var filesInput = document.getElementById("jarvis-files");
    var rewriteInput = document.getElementById("jarvis-rewrite");
    if (!filesInput.files.length) {
      setStatus("Выберите хотя бы один файл.", true);
      return;
    }

    var formData = new FormData();
    formData.append("site_url", jarvisBridgeConfig.siteUrl);
    formData.append("rewrite_with_ai", rewriteInput.checked ? "true" : "false");
    for (var i = 0; i < filesInput.files.length; i += 1) {
      formData.append("files", filesInput.files[i]);
    }

    setStatus("Отправляю файлы NABVE…", false);

    fetch(jarvisBridgeConfig.backendUrl + "/api/wordpress/upload", {
      method: "POST",
      headers: { "X-Assistant-Token": jarvisBridgeConfig.apiToken },
      body: formData,
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        setStatus("NABVE готовит черновик — сейчас откроется видимое окно браузера на этом компьютере…", false);
        pollJob(data.job_id, 0);
      })
      .catch(function (error) {
        setStatus("Не удалось связаться с NABVE: " + error.message, true);
      });
  });
})();
