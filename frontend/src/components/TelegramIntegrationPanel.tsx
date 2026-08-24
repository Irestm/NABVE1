import { useEffect, useState } from "react";
import {
  addTelegramContact,
  deleteTelegramAccount,
  deleteTelegramContact,
  getTelegramCredentialsStatus,
  listTelegramAccounts,
  listTelegramContacts,
  saveTelegramCredentials,
  startTelegramLogin,
  submitTelegramLoginCode,
  submitTelegramLoginPassword,
} from "../api/client";
import type { TelegramAccount, TelegramContact, TelegramCredentialsStatus } from "../types";
import "./TelegramIntegrationPanel.css";

type LoginStep = "idle" | "phone" | "code" | "password";

const MAX_ACCOUNTS = 3;
const MAX_CONTACTS = 5;

export function TelegramIntegrationPanel(): JSX.Element {
  const [credentials, setCredentials] = useState<TelegramCredentialsStatus | null>(null);
  const [apiIdInput, setApiIdInput] = useState("");
  const [apiHashInput, setApiHashInput] = useState("");
  const [accounts, setAccounts] = useState<TelegramAccount[]>([]);
  const [contacts, setContacts] = useState<TelegramContact[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [loginStep, setLoginStep] = useState<LoginStep>("idle");
  const [loginToken, setLoginToken] = useState("");
  const [labelInput, setLabelInput] = useState("");
  const [phoneInput, setPhoneInput] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [passwordInput, setPasswordInput] = useState("");
  const [contactInput, setContactInput] = useState("");

  async function refresh(): Promise<void> {
    try {
      const [creds, accs, cts] = await Promise.all([
        getTelegramCredentialsStatus(),
        listTelegramAccounts(),
        listTelegramContacts(),
      ]);
      setCredentials(creds);
      setAccounts(accs);
      setContacts(cts);
    } catch (err) {
      console.error("Failed to load Telegram integration state:", err);
      setError("Не удалось загрузить статус Telegram.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function handleSaveCredentials(): Promise<void> {
    const apiId = parseInt(apiIdInput, 10);
    if (!apiId || !apiHashInput.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      setCredentials(await saveTelegramCredentials(apiId, apiHashInput.trim()));
      setApiIdInput("");
      setApiHashInput("");
    } catch (err) {
      console.error("Failed to save Telegram app credentials:", err);
      setError(err instanceof Error ? err.message : "Не удалось сохранить api_id/api_hash.");
    } finally {
      setBusy(false);
    }
  }

  function resetLoginForm(): void {
    setLoginStep("idle");
    setLoginToken("");
    setLabelInput("");
    setPhoneInput("");
    setCodeInput("");
    setPasswordInput("");
  }

  async function handleStartLogin(): Promise<void> {
    if (!labelInput.trim() || !phoneInput.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const token = await startTelegramLogin(labelInput.trim(), phoneInput.trim());
      setLoginToken(token);
      setLoginStep("code");
    } catch (err) {
      console.error("Failed to start Telegram login:", err);
      setError(err instanceof Error ? err.message : "Не удалось начать вход.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitCode(): Promise<void> {
    if (!codeInput.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await submitTelegramLoginCode(loginToken, codeInput.trim());
      if (result.needs_password) {
        setLoginStep("password");
      } else {
        resetLoginForm();
        await refresh();
      }
    } catch (err) {
      console.error("Failed to submit Telegram login code:", err);
      setError(err instanceof Error ? err.message : "Не удалось подтвердить код.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitPassword(): Promise<void> {
    if (!passwordInput.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await submitTelegramLoginPassword(loginToken, passwordInput.trim());
      resetLoginForm();
      await refresh();
    } catch (err) {
      console.error("Failed to submit Telegram 2FA password:", err);
      setError(err instanceof Error ? err.message : "Не удалось подтвердить пароль.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteAccount(accountId: number): Promise<void> {
    setBusy(true);
    setError("");
    try {
      await deleteTelegramAccount(accountId);
      setAccounts((current) => current.filter((a) => a.id !== accountId));
    } catch (err) {
      console.error("Failed to delete Telegram account:", err);
      setError(err instanceof Error ? err.message : "Не удалось удалить аккаунт.");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddContact(): Promise<void> {
    if (!contactInput.trim()) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const contact = await addTelegramContact(contactInput.trim());
      setContacts((current) => [...current, contact]);
      setContactInput("");
    } catch (err) {
      console.error("Failed to add a watched Telegram contact:", err);
      setError(err instanceof Error ? err.message : "Не удалось добавить контакт.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteContact(contactId: number): Promise<void> {
    setBusy(true);
    setError("");
    try {
      await deleteTelegramContact(contactId);
      setContacts((current) => current.filter((c) => c.id !== contactId));
    } catch (err) {
      console.error("Failed to delete a watched Telegram contact:", err);
      setError(err instanceof Error ? err.message : "Не удалось удалить контакт.");
    } finally {
      setBusy(false);
    }
  }

  if (credentials === null) {
    return <></>;
  }

  return (
    <div className="settings-panel__field telegram-integration">
      <span className="settings-panel__label">Telegram (личный аккаунт)</span>
      <p className="status-detail">
        Вход как в обычный Telegram, не через бота — доступ к вашим личным перепискам, относитесь к нему как к
        паролю от аккаунта. До {MAX_ACCOUNTS} аккаунтов, до {MAX_CONTACTS} избранных контактов (общий список на
        все аккаунты).
      </p>
      {error && <p className="status-error">{error}</p>}

      {!credentials.configured ? (
        <>
          <p className="status-detail">
            Сначала свои api_id/api_hash с my.telegram.org/apps — бесплатно, один раз на всё приложение.
          </p>
          <div className="row">
            <input
              type="text"
              value={apiIdInput}
              onChange={(event) => setApiIdInput(event.target.value)}
              placeholder="api_id"
            />
            <input
              type="password"
              value={apiHashInput}
              onChange={(event) => setApiHashInput(event.target.value)}
              placeholder="api_hash"
            />
            <button type="button" onClick={() => void handleSaveCredentials()} disabled={busy}>
              Сохранить
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="settings-panel__success">api_id/api_hash заданы.</p>

          {accounts.map((account) => (
            <div key={account.id} className="telegram-integration__account row">
              <span>
                {account.label} ({account.phone_number}) — {account.connected ? "подключён" : "не подключён"}
              </span>
              <button type="button" onClick={() => void handleDeleteAccount(account.id)} disabled={busy}>
                Отключить
              </button>
            </div>
          ))}

          {accounts.length < MAX_ACCOUNTS && loginStep === "idle" && (
            <div className="row">
              <button type="button" onClick={() => setLoginStep("phone")} disabled={busy}>
                + Добавить аккаунт
              </button>
            </div>
          )}
          {loginStep === "phone" && (
            <div className="row">
              <input
                type="text"
                value={labelInput}
                onChange={(event) => setLabelInput(event.target.value)}
                placeholder="Метка (например, Личный)"
              />
              <input
                type="text"
                value={phoneInput}
                onChange={(event) => setPhoneInput(event.target.value)}
                placeholder="+380..."
              />
              <button type="button" onClick={() => void handleStartLogin()} disabled={busy}>
                Отправить код
              </button>
            </div>
          )}
          {loginStep === "code" && (
            <div className="row">
              <input
                type="text"
                value={codeInput}
                onChange={(event) => setCodeInput(event.target.value)}
                placeholder="Код из Telegram"
              />
              <button type="button" onClick={() => void handleSubmitCode()} disabled={busy}>
                Подтвердить
              </button>
            </div>
          )}
          {loginStep === "password" && (
            <div className="row">
              <input
                type="password"
                value={passwordInput}
                onChange={(event) => setPasswordInput(event.target.value)}
                placeholder="Облачный пароль (2FA)"
              />
              <button type="button" onClick={() => void handleSubmitPassword()} disabled={busy}>
                Подтвердить
              </button>
            </div>
          )}

          <span className="settings-panel__label">
            Избранные контакты ({contacts.length}/{MAX_CONTACTS})
          </span>
          {contacts.map((contact) => (
            <div key={contact.id} className="row">
              <span>{contact.identifier}</span>
              <button type="button" onClick={() => void handleDeleteContact(contact.id)} disabled={busy}>
                Удалить
              </button>
            </div>
          ))}
          {contacts.length < MAX_CONTACTS && (
            <div className="row">
              <input
                type="text"
                value={contactInput}
                onChange={(event) => setContactInput(event.target.value)}
                placeholder="@username"
              />
              <button type="button" onClick={() => void handleAddContact()} disabled={busy}>
                Добавить
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
