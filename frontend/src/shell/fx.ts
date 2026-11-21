// Prism interaction layer: one set of delegated listeners drives every pointer effect in the studio.
//   · spotlight   any [data-glow] / .button / .chip / .card / .reel gets --px/--py (pointer position, px)
//   · tilt        [data-tilt] elements lean toward the pointer (--rx/--ry, degrees)
//   · magnetic    [data-magnetic] elements drift toward the pointer (--mx/--my, px)
//   · ripple      pointerdown on buttons drops an expanding light ring
//   · ambient     <html> carries --cx/--cy (0..1) so backgrounds can follow the cursor
// Everything is rAF-batched and honours reduced motion (data-motion="off" / prefers-reduced-motion).
import { motionReduced } from "../design/appearance";

const GLOW = "[data-glow], .ui-button, .button, .btn, .chip, .card, .reel, .tool-btn, .gr-take, .settings-card, .workflow-card, .asset-card, .cmdk-item";
const RIPPLE = ".ui-button, .button, .btn, .chip, .dock-btn, .icon-button, .tool-btn, .seg button, .top-tray, .engine-pill, .cmdk-trigger";

let installed = false;

export function installFx() {
  if (installed || typeof window === "undefined") return () => undefined;
  installed = true;
  const root = document.documentElement;
  let frame = 0;
  let last: PointerEvent | null = null;
  let tilted: HTMLElement | null = null;
  let magnet: HTMLElement | null = null;

  const release = (el: HTMLElement | null, kind: "tilt" | "magnet") => {
    if (!el) return;
    if (kind === "tilt") { el.style.removeProperty("--rx"); el.style.removeProperty("--ry"); el.removeAttribute("data-tilting"); }
    else { el.style.removeProperty("--mx"); el.style.removeProperty("--my"); }
  };

  const paint = () => {
    frame = 0;
    const event = last;
    if (!event) return;
    root.style.setProperty("--cx", (event.clientX / window.innerWidth).toFixed(4));
    root.style.setProperty("--cy", (event.clientY / window.innerHeight).toFixed(4));
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const glow = target.closest<HTMLElement>(GLOW);
    if (glow) {
      const box = glow.getBoundingClientRect();
      glow.style.setProperty("--px", `${(event.clientX - box.left).toFixed(1)}px`);
      glow.style.setProperty("--py", `${(event.clientY - box.top).toFixed(1)}px`);
    }
    if (motionReduced()) return;
    const tilt = target.closest<HTMLElement>("[data-tilt]");
    if (tilt !== tilted) { release(tilted, "tilt"); tilted = tilt; }
    if (tilt) {
      const box = tilt.getBoundingClientRect();
      const strength = Number(tilt.dataset.tilt) || 9;
      const x = (event.clientX - box.left) / box.width - 0.5;
      const y = (event.clientY - box.top) / box.height - 0.5;
      tilt.style.setProperty("--ry", `${(x * strength).toFixed(2)}deg`);
      tilt.style.setProperty("--rx", `${(-y * strength).toFixed(2)}deg`);
      tilt.setAttribute("data-tilting", "");
    }
    const mag = target.closest<HTMLElement>("[data-magnetic]");
    if (mag !== magnet) { release(magnet, "magnet"); magnet = mag; }
    if (mag) {
      const box = mag.getBoundingClientRect();
      const pull = Number(mag.dataset.magnetic) || 0.22;
      mag.style.setProperty("--mx", `${((event.clientX - box.left - box.width / 2) * pull).toFixed(1)}px`);
      mag.style.setProperty("--my", `${((event.clientY - box.top - box.height / 2) * pull).toFixed(1)}px`);
    }
  };

  const move = (event: PointerEvent) => {
    if (event.pointerType === "touch") return;
    last = event;
    if (!frame) frame = requestAnimationFrame(paint);
  };
  const leave = () => { release(tilted, "tilt"); release(magnet, "magnet"); tilted = magnet = null; };

  const ripple = (event: PointerEvent) => {
    if (event.button !== 0 || motionReduced()) return;
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>(RIPPLE) : null;
    if (!target || (target as HTMLButtonElement).disabled) return;
    const box = target.getBoundingClientRect();
    const size = Math.max(box.width, box.height) * 2.2;
    const ring = document.createElement("span");
    ring.className = "fx-ripple";
    ring.style.cssText = `width:${size}px;height:${size}px;left:${event.clientX - box.left - size / 2}px;top:${event.clientY - box.top - size / 2}px`;
    if (getComputedStyle(target).position === "static") target.style.position = "relative";
    target.appendChild(ring);
    ring.addEventListener("animationend", () => ring.remove(), { once: true });
    window.setTimeout(() => ring.remove(), 1200);
  };

  document.addEventListener("pointermove", move, { passive: true });
  document.addEventListener("pointerleave", leave);
  document.addEventListener("pointerdown", ripple, { passive: true });
  return () => {
    installed = false;
    cancelAnimationFrame(frame);
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerleave", leave);
    document.removeEventListener("pointerdown", ripple);
  };
}

type ViewTransition = { finished: Promise<void>; ready: Promise<void>; updateCallbackDone: Promise<void> };
type ViewTransitionDocument = Document & { startViewTransition?: (cb: () => void) => ViewTransition };

/** Run a DOM-changing callback inside a View Transition when the browser supports it. */
export function withViewTransition(update: () => void, kind = "route") {
  const doc = document as ViewTransitionDocument;
  if (!doc.startViewTransition || motionReduced() || document.hidden) { update(); return; }
  document.documentElement.dataset.vt = kind;
  const transition = doc.startViewTransition(update);
  // A newer navigation skips this one: the DOM update still applies, only the animation is dropped.
  transition.ready.catch(() => undefined);
  transition.updateCallbackDone.catch(() => undefined);
  transition.finished.catch(() => undefined).finally(() => { delete document.documentElement.dataset.vt; });
}
