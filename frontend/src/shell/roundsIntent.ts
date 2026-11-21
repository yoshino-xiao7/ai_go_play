// Hand-off "open this card's result rounds" from outside the canvas (the tray, another view).
// Session-scoped and single use. When the canvas is already open it hears the event directly;
// otherwise it consumes the stored intent once the project has loaded.
export type RoundsIntent = { projectId: string; nodeId: string; version?: string; at: number };
const key = "manju:open-rounds";

export function requestRounds(projectId: string, nodeId: string, version?: string) {
  try { sessionStorage.setItem(key, JSON.stringify({ projectId, nodeId, version, at: Date.now() })); } catch { /* the event below still reaches an open canvas */ }
  window.dispatchEvent(new CustomEvent("manju:open-rounds", { detail: { projectId, nodeId, version } }));
}

export function takeRoundsIntent(projectId: string): RoundsIntent | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const intent = JSON.parse(raw) as RoundsIntent;
    if (intent.projectId !== projectId) return null;
    sessionStorage.removeItem(key);
    return Date.now() - intent.at < 60_000 ? intent : null;
  } catch { return null; }
}

/** The canvas heard the event itself: drop the stored copy so a later reload does not reopen it. */
export function clearRoundsIntent() {
  try { sessionStorage.removeItem(key); } catch { /* nothing stored */ }
}
