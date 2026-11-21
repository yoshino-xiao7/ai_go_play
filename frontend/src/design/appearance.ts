import { useSyncExternalStore } from "react";

// Workbench appearance: colour palette and motion preference.
// Prism ships two palettes over the same semantic tokens (studio/tokens.css):
//   nocturne — the default: ink-black stage, holographic spectrum light;
//   pearl    — opal daylight with the same spectrum, for bright rooms.
// Motion "reduce" sets html[data-motion="off"]; "system" defers to prefers-reduced-motion.
// Older stored values ("darkroom", "pale-pink") map onto the nearest Prism palette.

export type Palette = "nocturne" | "pearl";
export type MotionPreference = "system" | "reduce";

const paletteKey = "manju:appearance:palette";
const motionKey = "manju:appearance:motion";
const event = "manju:appearance";

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* Private mode: keep the in-page choice only. */ }
}

export function currentPalette(): Palette {
  const stored = read(paletteKey);
  return stored === "pearl" || stored === "pale-pink" ? "pearl" : "nocturne";
}
export function currentMotion(): MotionPreference {
  return read(motionKey) === "reduce" ? "reduce" : "system";
}

export function applyAppearance(palette = currentPalette(), motion = currentMotion()) {
  const root = document.documentElement;
  root.dataset.palette = palette;
  if (motion === "reduce") root.dataset.motion = "off";
  else delete root.dataset.motion;
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute("content", palette === "pearl" ? "#f6f1fa" : "#07060c");
}

export function setPalette(palette: Palette) {
  write(paletteKey, palette);
  const apply = () => applyAppearance(palette, currentMotion());
  // A palette switch is a show: cross-fade the whole studio when the browser supports it.
  type Transition = { ready: Promise<void>; finished: Promise<void>; updateCallbackDone: Promise<void> };
  const doc = document as Document & { startViewTransition?: (cb: () => void) => Transition };
  if (doc.startViewTransition && !motionReduced()) {
    const transition = doc.startViewTransition(apply);
    for (const done of [transition.ready, transition.finished, transition.updateCallbackDone]) done.catch(() => undefined);
  } else apply();
  window.dispatchEvent(new CustomEvent(event));
}
export function setMotion(motion: MotionPreference) {
  write(motionKey, motion);
  applyAppearance(currentPalette(), motion);
  window.dispatchEvent(new CustomEvent(event));
}
// Another tab changed the look: apply it here too, so html[data-palette] and usePalette() never disagree.
if (typeof window !== "undefined") {
  window.addEventListener("storage", change => {
    if (change.key !== paletteKey && change.key !== motionKey) return;
    applyAppearance();
    window.dispatchEvent(new CustomEvent(event));
  });
}

export function onAppearanceChange(listener: () => void) {
  window.addEventListener(event, listener);
  return () => window.removeEventListener(event, listener);
}

/** React subscription to the palette (e.g. React Flow's colorMode must follow it). */
export function usePalette(): Palette {
  return useSyncExternalStore(onAppearanceChange, currentPalette, () => "nocturne");
}

/** True when animations should be skipped (user choice or system setting). */
export function motionReduced() {
  return document.documentElement.dataset.motion === "off" ||
    (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches);
}

/** React subscription to the motion preference (for JS-driven effects). */
export function useMotionReduced(): boolean {
  return useSyncExternalStore(
    listener => {
      const media = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
      media?.addEventListener("change", listener);
      const off = onAppearanceChange(listener);
      return () => { media?.removeEventListener("change", listener); off(); };
    },
    motionReduced,
    () => false,
  );
}
