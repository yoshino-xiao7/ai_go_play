import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, X, LoaderCircle } from "lucide-react";
import { useLayer } from "./shell/layers";

export function Modal({
  title,
  children,
  onClose,
  wide = false,
  className = "",
  page = false,
  backLabel,
  returnTo,
  closeLabel,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  className?: string;
  /** Fill the shell stage as a view instead of floating over a scrim. */
  page?: boolean;
  /** Page views show a labelled way back (e.g. "返回画布") instead of a bare ×. */
  backLabel?: string;
  /** Where focus goes on close when the control that opened the dialog is gone (e.g. a menu item). */
  returnTo?: () => HTMLElement | null;
  closeLabel?: string;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  // Esc closes only the topmost layer; focus returns to the control that opened this dialog.
  const isTop = useLayer(true, onClose, { ref: dialog, fallback: returnTo });
  useEffect(() => {
    const initial = dialog.current?.querySelector<HTMLElement>(
      "[data-autofocus], input:not([type='hidden']):not([disabled]), textarea:not([disabled]), select:not([disabled])",
    );
    (initial || dialog.current)?.focus({ preventScroll: true });
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialog.current || !isTop()) return;
      const focusable = Array.from(
        dialog.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
        ),
      ).filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!dialog.current.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  // Floating dialogs render at the document root: opened from inside a blurred or transformed
  // container (the top bar, a card) they would otherwise be positioned and clipped by it.
  const view = (
    <div
      className={`modal-shade ${page ? "is-page" : ""}`}
      onMouseDown={(event) => {
        if (!page && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? "modal-wide" : ""} ${page ? "is-page" : ""} ${className}`}
        role="dialog"
        aria-modal={page ? undefined : true}
        aria-label={title}
        tabIndex={-1}
        ref={dialog}
      >
        <header className="modal-heading">
          {page && (
            <button className="modal-back" onClick={onClose}>
              <ArrowLeft size={16} />
              <span>{backLabel || "返回"}</span>
            </button>
          )}
          <h2>{title}</h2>
          <button className={closeLabel ? "button secondary" : "icon-button"}
            aria-label={closeLabel || (page ? `关闭${title}` : "关闭")} title="关闭 (Esc)" onClick={onClose}>
            <X size={closeLabel ? 15 : 19} />
            {closeLabel}
          </button>
        </header>
        {children}
      </div>
    </div>
  );
  // page views live in the shell stage (their place in the layout); floating dialogs go to the root
  return page ? view : createPortal(view, document.body);
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle size={22} className="spin" />
      <span>正在读取本地资料库</span>
    </div>
  );
}

export function Confirm({
  title,
  description,
  onConfirm,
  onClose,
  busy = false,
}: {
  title: string;
  description: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <div className="modal-body">
        <p className="confirm-copy">{description}</p>
      </div>
      <footer className="modal-footer">
        <button className="button secondary" onClick={onClose}>
          取消
        </button>
        <button disabled={busy} className="button danger" onClick={onConfirm}>
          {busy ? "处理中…" : "确认"}
        </button>
      </footer>
    </Modal>
  );
}
