// One stack for everything that floats: dialogs, menus, popovers, flyouts and side sheets.
//
//  · Esc closes only the topmost layer. The listener sits on document in the bubble phase, so a
//    component that handles Esc itself (a select, the @mention picker, inline rename) still wins by
//    calling preventDefault/stopPropagation, and the canvas's window-level Esc (deselect) only runs
//    when no layer took the key.
//  · "focus" scoped layers (side sheets, drawers) take Esc only while focus is inside them, so Esc
//    on the canvas still deselects instead of folding a panel away.
//  · outside: true closes on a pointerdown outside the layer (menus, popovers).
//  · On close, focus goes back to whatever opened the layer (or a fallback when that control is
//    gone), unless the user already moved focus somewhere else on purpose.
import { useEffect, useRef } from "react";
import type { RefObject } from "react";

type Layer = {
  id: number;
  close: () => void;
  element: () => HTMLElement | null;
  scope: "global" | "focus";
  outside: boolean;
  ignore?: (target: Element) => boolean;
};

const stack: Layer[] = [];
let serial = 0;
/** Recent controls that got a pointer or focus, newest last (a layer that autofocuses its own field
 *  during render pushes that field before the layer registers, so the opener is the newest entry
 *  that lies outside the new layer). */
const recent: HTMLElement[] = [];
let lastPointer: Element | null = null;
let installed = false;

const interactive = "button, a[href], [role='button'], [role='menuitem'], [role='tab'], input, select, textarea, summary, [tabindex]:not([tabindex='-1'])";

function install() {
  if (installed || typeof document === "undefined") return;
  installed = true;
  // Remember the control that most recently got a pointer or focus: it is the opener of whatever
  // appears next, even when the new layer moves focus into itself during render (autoFocus).
  const remember = (event: Event) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>(interactive) : null;
    if (!target) return;
    const at = recent.indexOf(target);
    if (at >= 0) recent.splice(at, 1);
    recent.push(target);
    if (recent.length > 8) recent.shift();
  };
  document.addEventListener("pointerdown", event => { lastPointer = event.target instanceof Element ? event.target : null; remember(event); }, true);
  document.addEventListener("focusin", remember, true);
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || event.defaultPrevented || event.isComposing) return;
    const active = document.activeElement;
    for (let index = stack.length - 1; index >= 0; index--) {
      const layer = stack[index];
      const element = layer.element();
      // focus-scoped: focus is inside, or focus fell to <body> after a click inside (on plain text,
      // a thumbnail, the panel background), which still means the user is working in this sheet
      const inside = !!element && ((!!active && active !== document.body && element.contains(active)) || ((!active || active === document.body) && !!lastPointer && element.contains(lastPointer)));
      if (layer.scope === "focus" && !inside) continue;
      event.preventDefault();
      event.stopPropagation();
      layer.close();
      return;
    }
  });
  document.addEventListener("pointerdown", event => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    // Only the topmost outside-dismissable layers close, and never because of a click that lands
    // inside a layer stacked above them (a select popup inside a popover, for instance).
    for (let index = stack.length - 1; index >= 0; index--) {
      const layer = stack[index];
      const element = layer.element();
      if (element?.contains(target)) return;
      if (!layer.outside) return;
      if (layer.ignore?.(target)) return;
      layer.close();
    }
  }, true);
}

function visible(element: HTMLElement | null): element is HTMLElement {
  return !!element && element.isConnected && element.getClientRects().length > 0 && !(element as HTMLButtonElement).disabled;
}

export type LayerOptions = {
  ref?: RefObject<HTMLElement | null>;
  scope?: "global" | "focus";
  outside?: boolean;
  /** Return focus to the opener on close (default true). */
  returnFocus?: boolean;
  /** Where focus goes when the opener is gone: a selector or a function. */
  fallback?: string | (() => HTMLElement | null);
  /** Pointerdowns on these targets do not count as "outside" (e.g. the toggle that opened it). */
  ignore?: (target: Element) => boolean;
};

/** Register a layer while `active`. Returns a function telling whether it is the topmost layer. */
export function useLayer(active: boolean, close: () => void, options: LayerOptions = {}) {
  const closeRef = useRef(close);
  closeRef.current = close;
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const idRef = useRef(0);
  useEffect(() => {
    if (!active) return;
    install();
    const id = ++serial;
    idRef.current = id;
    const element = () => optionsRef.current.ref?.current ?? null;
    const own = element();
    const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const outsideOwn = (element: HTMLElement | null) => !!element && element.isConnected && !(own && own.contains(element));
    // The opener is the newest recent control outside the layer, or a disclosure button
    // (aria-expanded) even when the layer container also holds it (menu wrappers, tool spines).
    // An autofocused field inside the new layer is never the opener.
    const disclosure = (element: HTMLElement) => element.isConnected && element.hasAttribute("aria-expanded");
    const opener = [...recent].reverse().find(element => outsideOwn(element) || disclosure(element)) ?? (outsideOwn(focused) ? focused : null);
    stack.push({
      id, close: () => closeRef.current(), element,
      scope: optionsRef.current.scope ?? "global", outside: !!optionsRef.current.outside,
      ignore: target => !!optionsRef.current.ignore?.(target) || (!!opener && opener.contains(target)),
    });
    return () => {
      const index = stack.findIndex(layer => layer.id === id);
      if (index >= 0) stack.splice(index, 1);
      if (optionsRef.current.returnFocus === false) return;
      const layerElement = own;
      requestAnimationFrame(() => {
        const now = document.activeElement;
        // the user already put focus somewhere meaningful: leave it there
        if (now && now !== document.body && now.isConnected && !(layerElement && layerElement.contains(now))) return;
        const { fallback } = optionsRef.current;
        const target = visible(opener) ? opener
          : typeof fallback === "function" ? fallback()
          : typeof fallback === "string" ? document.querySelector<HTMLElement>(fallback) : null;
        if (visible(target)) target.focus({ preventScroll: true });
      });
    };
  }, [active]);
  return () => stack.length > 0 && stack[stack.length - 1].id === idRef.current;
}

// listen from the first moment, so the control that opens the very first layer is known too
install();
