// The open canvas registers how to flush its pending save, so shell-level actions
// (exit, leaving through the rail) never drop an edit. One canvas is open at a time.
let flushCanvas: (() => Promise<void>) | null = null;

export function registerCanvasFlush(flush: (() => Promise<void>) | null) {
  flushCanvas = flush;
}

export async function flushOpenCanvas() {
  if (flushCanvas) await flushCanvas();
}

/** Commands the shell's top bar sends to the open canvas. */
export type CanvasCommand = "share" | "export" | "production" | "orchestrate" | "lipsync" | "drafts" | "search";
export function sendCanvasCommand(command: CanvasCommand) {
  window.dispatchEvent(new CustomEvent("manju:canvas-command", { detail: { command } }));
}

const lastProjectKey = "manju:last-project";
export function rememberProject(id: string) {
  try { localStorage.setItem(lastProjectKey, id); } catch { /* optional convenience */ }
}
export function lastProject(): string | null {
  try { return localStorage.getItem(lastProjectKey); } catch { return null; }
}
export function forgetProject(id: string) {
  try { if (localStorage.getItem(lastProjectKey) === id) localStorage.removeItem(lastProjectKey); } catch { /* optional */ }
}
