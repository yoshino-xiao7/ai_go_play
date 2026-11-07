import type { AssetVersion } from "./types";

export type SubjectKind = "character" | "scene" | "prop";

export type SubjectSnapshot = {
  kind: SubjectKind;
  name: string;
  description: string;
  image_version_ids: string[];
  voice_version_id?: string | null;
  voice_name?: string;
  voice_transcript?: string;
  library_id?: string;
};

export type SubjectMediaCandidate = {
  version_id: string;
  title: string;
  kind: "image" | "audio";
  node_id?: string;
};

export const subjectKindLabels: Record<SubjectKind, string> = {
  character: "人物", scene: "场景", prop: "道具",
};

export type Subject = {
  id: string;
  name: string;
  description: string;
  version_id: string;
  asset_id: string;
  created_at: string;
  updated_at: string;
  version: AssetVersion;
  kind: SubjectKind;
  image_version_ids: string[];
  images: AssetVersion[];
  voice_version_id: string | null;
  voice_name: string;
  voice_transcript: string;
  voice: AssetVersion | null;
};

export type SubjectPage = { items: Subject[]; total: number };

// Old library entries only carried one version_id. Keep their fixed version
// when opening them in the new editor or copying them onto a canvas.
export function subjectSnapshot(subject: Subject): SubjectSnapshot {
  const kind = subject.kind && subject.kind in subjectKindLabels ? subject.kind : "character";
  return {
    kind,
    name: subject.name,
    description: subject.description || "",
    image_version_ids: [...new Set(subject.image_version_ids?.length ? subject.image_version_ids : subject.version_id ? [subject.version_id] : [])],
    voice_version_id: kind === "character" ? subject.voice_version_id || null : null,
    voice_name: kind === "character" ? subject.voice_name || "" : "",
    voice_transcript: kind === "character" ? subject.voice_transcript || "" : "",
    library_id: subject.id,
  };
}
