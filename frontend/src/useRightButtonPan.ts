import { useEffect, useRef, type RefObject } from "react";
import type { Viewport } from "@xyflow/react";

// Own the secondary-button gesture before node dragging or browser defaults.
// A stationary click still reaches the existing node/edge/pane context menu.
export function useRightButtonPan(
  stage: RefObject<HTMLElement | null>,
  getViewport: () => Viewport,
  setViewport: (viewport: Viewport) => unknown,
  onStart: () => void,
) {
  const actions = useRef({ getViewport, setViewport, onStart });
  actions.current = { getViewport, setViewport, onStart };
  useEffect(() => {
    const element = stage.current;
    if (!element) return;
    let gesture: { id: number; x: number; y: number; viewport: Viewport } | null = null;
    let moved = false;
    let frame = 0;
    let next: Viewport | null = null;
    const flush = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      if (next) { actions.current.setViewport(next); next = null; }
    };
    const down = (event: PointerEvent) => {
      moved = false;
      if (event.button !== 2 || !(event.target instanceof Element) ||
          !event.target.closest(".react-flow") ||
          event.target.closest('input,textarea,select,[contenteditable="true"],.react-flow__controls,.react-flow__minimap')) return;
      gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, viewport: actions.current.getViewport() };
      event.preventDefault();
      event.stopPropagation();
    };
    const move = (event: PointerEvent) => {
      if (!gesture || event.pointerId !== gesture.id) return;
      if (!(event.buttons & 2)) { end(); return; }
      const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y;
      if (!moved && Math.hypot(dx, dy) < 5) return;
      if (!moved) { moved = true; actions.current.onStart(); element.classList.add("right-button-panning"); }
      event.preventDefault();
      event.stopPropagation();
      next = { ...gesture.viewport, x: gesture.viewport.x + dx, y: gesture.viewport.y + dy };
      if (!frame) frame = requestAnimationFrame(flush);
    };
    const end = () => { flush(); gesture = null; element.classList.remove("right-button-panning"); };
    const up = (event: PointerEvent) => { if (gesture?.id === event.pointerId) end(); };
    const context = (event: MouseEvent) => {
      if (!moved) return;
      event.preventDefault(); event.stopPropagation();
    };
    element.addEventListener("pointerdown", down, true);
    element.addEventListener("contextmenu", context, true);
    window.addEventListener("pointermove", move, { capture: true, passive: false });
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    window.addEventListener("blur", end);
    return () => {
      cancelAnimationFrame(frame);
      element.classList.remove("right-button-panning");
      element.removeEventListener("pointerdown", down, true);
      element.removeEventListener("contextmenu", context, true);
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
      window.removeEventListener("blur", end);
    };
  }, [stage]);
}
