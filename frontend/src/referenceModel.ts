import type { ImageReference, PromptPart } from "./generationTypes";

export const referenceId = (reference: ImageReference) => reference.id || `ref-${reference.version_id}`;

// Delete a manual reference only when its last mention was removed. Connections
// and material explicitly added without a mention remain independent of text.
export function referencesAfterPromptEdit(previous: string, next: string, references: ImageReference[]) {
  const mentioned = (text: string) => new Set(promptParts(text, references).flatMap(part => part.type === "reference" ? [part.reference_id] : []));
  const before = mentioned(previous), after = mentioned(next);
  return references.filter(ref => ref.source !== "mention" || !before.has(referenceId(ref)) || after.has(referenceId(ref)));
}

export function normalizeVideoReferences(prompt: string, references: ImageReference[]) {
  const canonical = new Map<string, ImageReference>();
  const key = (ref: ImageReference) => JSON.stringify([ref.version_id,ref.role||"reference",ref.fit||"contain",ref.purpose||"general",!!ref.use_audio,ref.crop?.x||0,ref.crop?.y||0,ref.crop?.width??1,ref.crop?.height??1,ref.clip_start||0,ref.clip_end??null]);
  for (const ref of references) {
    const existing = canonical.get(key(ref));
    if (!existing || (ref.source === "connection" && existing.source !== "connection")) canonical.set(key(ref), ref);
  }
  const aliases = new Map(references.map(ref => [referenceId(ref), canonical.get(key(ref))!]));
  const clean = references.filter(ref => canonical.get(key(ref)) === ref || (ref.source === "connection" && canonical.get(key(ref))?.edge_id !== ref.edge_id));
  if (clean.length === references.length) return {prompt, references};
  // Parse frozen aliases longest-first, so e.g. “人物 · 2” never becomes “人物 · 2 · 2”.
  return {references: clean, prompt: promptParts(prompt, references).map(part => part.type === "text" ? part.text : `@${aliases.get(part.reference_id)!.title}`).join("")};
}

// Names are frozen aliases of a reference, never looked up against mutable node names.
export function promptParts(text: string, references: ImageReference[]): PromptPart[] {
  const names = [...references].sort((a,b) => b.title.length-a.title.length);
  const parts: PromptPart[] = [];
  let start = 0;
  for (let index=0; index<text.length; index++) {
    if (text[index] !== "@") continue;
    const match = names.find(ref => ref.title && text.startsWith(`@${ref.title}`, index));
    if (!match) continue;
    if (index>start) parts.push({ type:"text", text:text.slice(start,index) });
    parts.push({ type:"reference", reference_id:referenceId(match) });
    index += match.title.length;
    start=index+1;
  }
  if (start<text.length) parts.push({ type:"text", text:text.slice(start) });
  return parts;
}
