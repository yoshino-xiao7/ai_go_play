import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { ChevronRight } from "lucide-react";
import { useLayer } from "./shell/layers";

export type CanvasMenuItem = {
  id: string;
  label?: string;
  icon?: ReactNode;
  shortcut?: string;
  disabled?: boolean;
  hint?: string;
  danger?: boolean;
  divider?: boolean;
  onSelect?: () => void;
  children?: CanvasMenuItem[];
};

type Props = {
  position: { x: number; y: number };
  items: CanvasMenuItem[];
  onClose: () => void;
};

function MenuList({
  items,
  position,
  parentRect,
  onClose,
  onBack,
  label,
}: Props & {
  parentRect?: DOMRect;
  onBack?: () => void;
  label: string;
}) {
  const menu = useRef<HTMLDivElement>(null);
  // a submenu is its own layer: Esc or an outside click peels one level at a time
  useLayer(true, onBack || onClose, { ref: menu, outside: !onBack });
  const [location, setLocation] = useState(position);
  const [submenu, setSubmenu] = useState<{ id: string; rect: DOMRect } | null>(
    null,
  );
  const [openToLeft, setOpenToLeft] = useState(false);
  const submenuItem = items.find((item) => item.id === submenu?.id);
  useLayoutEffect(() => {
    const bounds = menu.current?.getBoundingClientRect();
    if (!bounds) return;
    let x = position.x;
    let y = position.y;
    if (parentRect) {
      const left = parentRect.right + bounds.width + 8 > window.innerWidth - 8;
      x = left ? parentRect.left - bounds.width - 5 : parentRect.right + 5;
      y = parentRect.top - 5;
      setOpenToLeft(left);
    }
    setLocation({
      x: Math.max(8, Math.min(x, window.innerWidth - bounds.width - 8)),
      y: Math.max(8, Math.min(y, window.innerHeight - bounds.height - 8)),
    });
  }, [position.x, position.y, parentRect]);
  useEffect(() => {
    menu.current
      ?.querySelector<HTMLButtonElement>(
        'button[role="menuitem"]:not(:disabled)',
      )
      ?.focus({ preventScroll: true });
  }, []);

  const choose = (item: CanvasMenuItem, button?: HTMLButtonElement) => {
    if (item.disabled) return;
    if (item.children) {
      const target =
        button ||
        menu.current?.querySelector<HTMLButtonElement>(
          `[data-menu-item="${item.id}"]`,
        );
      if (target)
        setSubmenu({ id: item.id, rect: target.getBoundingClientRect() });
      return;
    }
    onClose();
    item.onSelect?.();
  };
  return (
    <>
      <div
        ref={menu}
        role="menu"
        aria-label={label}
        data-canvas-context-menu
        className={`canvas-context-menu ${openToLeft ? "opens-left" : ""}`}
        style={{ left: location.x, top: location.y }}
        onContextMenu={(event) => event.preventDefault()}
        onKeyDown={(event) => {
          const buttons = Array.from(
            menu.current?.querySelectorAll<HTMLButtonElement>(
              ':scope > button[role="menuitem"]:not(:disabled)',
            ) || [],
          );
          const current = buttons.findIndex(
            (button) => button === document.activeElement,
          );
          if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            event.stopPropagation();
            const index =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? buttons.length - 1
                  : (current +
                      (event.key === "ArrowDown" ? 1 : -1) +
                      buttons.length) %
                    buttons.length;
            buttons[index]?.focus();
          } else if (event.key === "ArrowRight") {
            event.preventDefault();
            event.stopPropagation();
            const item = items.find(
              (entry) => entry.id === buttons[current]?.dataset.menuItem,
            );
            if (item?.children) choose(item, buttons[current]);
          } else if (event.key === "ArrowLeft" && onBack) {
            event.preventDefault();
            event.stopPropagation();
            onBack();
          } else if (event.key === "Escape" || event.key === "Tab") {
            event.stopPropagation();
            if (event.key === "Escape") event.preventDefault();
            onClose();
          } else {
            const shortcut = `${event.ctrlKey || event.metaKey ? "Ctrl+" : ""}${event.shiftKey ? "Shift+" : ""}${event.key.length === 1 ? event.key.toUpperCase() : event.key}`;
            const item = items.find(
              (entry) => entry.shortcut === shortcut && !entry.disabled,
            );
            if (item) {
              event.preventDefault();
              event.stopPropagation();
              choose(item);
            }
          }
        }}
      >
        {items.map((item) =>
          item.divider ? (
            <div
              className="canvas-context-separator"
              role="separator"
              key={item.id}
            />
          ) : (
            <button
              key={item.id}
              role="menuitem"
              data-menu-item={item.id}
              disabled={item.disabled}
              title={item.hint}
              aria-haspopup={item.children ? "menu" : undefined}
              aria-expanded={
                item.children ? submenu?.id === item.id : undefined
              }
              className={`${item.danger ? "danger" : ""} ${submenu?.id === item.id ? "submenu-open" : ""}`}
              onPointerEnter={(event) => {
                if (item.children && !item.disabled)
                  setSubmenu({
                    id: item.id,
                    rect: event.currentTarget.getBoundingClientRect(),
                  });
                else setSubmenu(null);
              }}
              onClick={(event) => choose(item, event.currentTarget)}
            >
              <span className="canvas-context-icon">{item.icon}</span>
              <span className="canvas-context-label">{item.label}</span>
              {item.shortcut && <kbd>{item.shortcut.replaceAll("+", " ")}</kbd>}
              {item.children && (
                <ChevronRight className="canvas-context-chevron" size={14} />
              )}
            </button>
          ),
        )}
      </div>
      {submenu && submenuItem?.children && (
        <MenuList
          key={submenu.id}
          items={submenuItem.children}
          position={{ x: submenu.rect.right + 5, y: submenu.rect.top }}
          parentRect={submenu.rect}
          label={submenuItem.label || "子菜单"}
          onClose={onClose}
          onBack={() => {
            const id = submenu.id;
            setSubmenu(null);
            menu.current
              ?.querySelector<HTMLButtonElement>(`[data-menu-item="${id}"]`)
              ?.focus();
          }}
        />
      )}
    </>
  );
}

export default function CanvasContextMenu({ position, items, onClose }: Props) {
  useEffect(() => {
    const dismissOutside = (event: Event) => {
      if (
        !(event.target instanceof Element) ||
        !event.target.closest("[data-canvas-context-menu]")
      )
        onClose();
    };
    document.addEventListener("pointerdown", dismissOutside, true);
    document.addEventListener("wheel", dismissOutside, true);
    document.addEventListener("scroll", dismissOutside, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside, true);
      document.removeEventListener("wheel", dismissOutside, true);
      document.removeEventListener("scroll", dismissOutside, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);
  return createPortal(
    <MenuList
      items={items}
      position={position}
      onClose={onClose}
      label="画布右键菜单"
    />,
    document.body,
  );
}
