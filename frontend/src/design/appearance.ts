import { useSyncExternalStore } from "react";

// Workbench appearance: colour palette and motion preference.
// The structural theme stays html[data-theme="studio"]; the palette only changes colours
// (pale-pink is the default light palette, darkroom is the original dark palette).
// Motion "reduce" sets html[data-motion="off"], which the motion layer and the
// pale-pink layer already honour; "system" defers to prefers-reduced-motion.

export type Palette = "pale-pink" | "darkroom";
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
  return read(paletteKey) === "darkroom" ? "darkroom" : "pale-pink";
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
  meta?.setAttribute("content", palette === "pale-pink" ? "#fbf3f5" : "#181617");
}

export function setPalette(palette: Palette) {
  write(paletteKey, palette);
  applyAppearance(palette, currentMotion());
  window.dispatchEvent(new CustomEvent(event));
}
export function setMotion(motion: MotionPreference) {
  write(motionKey, motion);
  applyAppearance(currentPalette(), motion);
  window.dispatchEvent(new CustomEvent(event));
}
export function onAppearanceChange(listener: () => void) {
  window.addEventListener(event, listener);
  return () => window.removeEventListener(event, listener);
}

/** React subscription to the palette (e.g. React Flow's colorMode must follow it). */
export function usePalette(): Palette {
  return useSyncExternalStore(onAppearanceChange, currentPalette, () => "pale-pink");
}

/** True when animations should be skipped (user choice or system setting). */
export function motionReduced() {
  return document.documentElement.dataset.motion === "off" ||
    (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches);
}
