// Hand-off from the project page to a canvas: "start a draft here". Session-scoped, single use,
// expires after five minutes, and only applies to the project it names. Nothing is submitted:
// the canvas creates a card with this description and the user decides when to generate.
export type DraftIntent = { projectId: string; kind: "image" | "video"; prompt: string; at: number };
const key = "manju:start-draft";

export function setDraftIntent(intent: Omit<DraftIntent, "at">) {
  try { sessionStorage.setItem(key, JSON.stringify({ ...intent, at: Date.now() })); } catch { /* the canvas still opens */ }
}

export function takeDraftIntent(projectId: string): DraftIntent | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const intent = JSON.parse(raw) as DraftIntent;
    if (intent.projectId !== projectId) return null;
    sessionStorage.removeItem(key);
    return Date.now() - intent.at < 5 * 60_000 && typeof intent.prompt === "string" ? intent : null;
  } catch { return null; }
}
