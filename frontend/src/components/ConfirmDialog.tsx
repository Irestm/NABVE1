import type { ReactNode } from "react";
import "./ConfirmDialog.css";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  busy?: boolean;
  confirmDisabled?: boolean;
  /** "danger" (default) for irreversible actions — red accents. "neutral"
   * for plain parameter-entry forms (e.g. create_folder) that just happen
   * to reuse this same overlay/panel shell. */
  tone?: "danger" | "neutral";
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

// Generic overlay, structured like BoardGameImageModal's backdrop+panel —
// reused both as the mandatory "are you sure?" step for dangerous commands
// in CommandPanel (delete_folder today — always shown BEFORE the backend
// call, in addition to, not instead of, the backend's own
// confirmation_required/token flow) and as a plain param-entry form shell
// for non-dangerous commands that need input (create_folder, set_volume, ...).
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Подтвердить",
  busy = false,
  confirmDisabled = false,
  tone = "danger",
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps): JSX.Element {
  return (
    <div className="confirm-overlay">
      <div className="confirm-overlay__backdrop" onClick={onCancel} />
      <div
        className={`confirm-panel${tone === "neutral" ? " confirm-panel--neutral" : ""}`}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
      >
        <h3 className="confirm-panel__title">{title}</h3>
        <p className="confirm-panel__message">{message}</p>
        {children}
        <div className="confirm-panel__actions">
          <button type="button" className="confirm-panel__cancel" onClick={onCancel} disabled={busy}>
            Отмена
          </button>
          <button
            type="button"
            className="confirm-panel__confirm"
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
          >
            {busy ? "..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
