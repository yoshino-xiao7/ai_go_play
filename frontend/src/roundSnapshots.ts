// Rounds = the real generation jobs of one canvas node, oldest first = round 1.
// Everything here reads the server snapshot (job.request); nothing writes to a job.
import type { GenerationDraft, GenerationJob, ImageReference } from "./generationTypes";
import type { WorkflowMode } from "./workflowTypes";

type SnapshotReference = {
  id?: string; version_id: string; node_id?: string | null; title?: string; description?: string;
  use_description?: boolean; role?: ImageReference["role"]; media_type?: ImageReference["media_type"];
  source?: ImageReference["source"]; edge_id?: string;
  // Frozen per reference by backend/manju/video_inputs.py normalize_inputs (H3 video rounds).
  fit?: ImageReference["fit"]; purpose?: ImageReference["purpose"]; use_audio?: boolean;
  crop?: ImageReference["crop"]; clip_start?: number; clip_end?: number | null;
};
type Snapshot = {
  kind?: "video" | "audio"; provider?: string; model?: string; quality?: string;
  workflow_id?: string; mode?: WorkflowMode; prompt?: string; negative_prompt?: string;
  prompt_parts?: GenerationDraft["prompt_parts"]; references?: SnapshotReference[];
  mask_version_id?: string | null; parameters?: Record<string, number | string>;
  video_mode?: GenerationDraft["video_mode"]; duration?: number; frame_count?: number; audio?: boolean;
  video_options?: GenerationDraft["video_options"]; h3_guides?: GenerationDraft["h3_guides"];
  speech_options?: GenerationDraft["speech_options"]; subject_node_id?: string;
};

/** Deep copy so the refilled draft never shares objects with the job record it came from. */
const copy = <T,>(value: T): T => value === undefined || value === null ? value : structuredClone(value);
/** Reference fields restored verbatim when the snapshot carries them (never taken from elsewhere). */
const FROZEN_REFERENCE_FIELDS = ["fit", "purpose", "use_audio", "crop", "clip_start", "clip_end"] as const;

export const snapshotOf = (job: GenerationJob) => (job.request || {}) as Snapshot;

/** Cloud requests leave this machine; local ones run on the workbench's ComfyUI. */
export function isCloudJob(job: GenerationJob) {
  const request = snapshotOf(job);
  return request.provider === "openai" || String((job as { backend_url?: string }).backend_url || "").startsWith("https://");
}

export function roundsOf(jobs: GenerationJob[], nodeId: string) {
  return jobs.filter(job => job.source_node_id === nodeId)
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((job, index) => ({ job, round: index + 1 }));
}

const SCALAR_PARAMETERS = ["width", "height", "steps", "cfg", "denoise", "seed"] as const;

/**
 * Build the node draft that reproduces a round. The job is never modified: the draft is a copy.
 * seed: "same" keeps the seed the server actually used; "random" asks for a new one (-1).
 * References are pinned to the exact versions of the snapshot (source "mention"), so a canvas
 * connection that now points at a newer version does not silently change the refilled round.
 */
export function draftFromRound(job: GenerationJob, current: GenerationDraft | undefined, nodeId: string,
  options: { seed: "same" | "random"; workflowMode?: WorkflowMode }): GenerationDraft {
  const request = snapshotOf(job);
  const references: ImageReference[] = (request.references || []).map((ref, index) => {
    const restored: ImageReference = {
      id: ref.id || `ref-${index + 1}-${ref.version_id.slice(0, 6)}`,
      version_id: ref.version_id,
      node_id: ref.node_id || undefined,
      title: ref.title || `参考 ${index + 1}`,
      description: ref.description,
      use_description: ref.use_description,
      role: ref.role,
      media_type: ref.media_type,
      source: "mention",
    };
    for (const key of FROZEN_REFERENCE_FIELDS)
      if (ref[key] !== undefined) (restored as Record<string, unknown>)[key] = copy(ref[key]);
    return restored;
  });
  // Parameters come only from the snapshot: a key the snapshot lacks is left to the composer's
  // defaults, never inherited from the current draft (that would pass another round off as this one).
  const parameters: Record<string, number | string> = {};
  for (const key of SCALAR_PARAMETERS) {
    const value = request.parameters?.[key];
    if (value !== undefined) parameters[key] = value;
  }
  if (options.seed === "random" && "seed" in parameters) parameters.seed = -1;
  const refill_of = { job_id: job.id, created_at: job.created_at, seed: typeof request.parameters?.seed === "number" ? Number(request.parameters.seed) : undefined };
  const base: GenerationDraft = {
    ...(current || { mode: "text_to_image", prompt: "", references: [], parameters: {} }),
    prompt: request.prompt || "",
    prompt_parts: copy(request.prompt_parts),
    workflow_id: request.workflow_id,
    // A refilled draft is a new request: drop both halves of any earlier unconfirmed submission.
    pending_submission: undefined,
    pending_request_id: undefined,
    refill_of,
  };
  if (request.kind === "video") {
    // Every field below is set explicitly, so an older snapshot without (say) frame_count clears the
    // draft's own value instead of reusing another round's exact frame count.
    return {
      ...base,
      kind: "video",
      video_mode: request.video_mode,
      duration: request.duration,
      frame_count: request.frame_count,
      audio: request.audio,
      video_options: copy(request.video_options),
      h3_guides: copy(request.h3_guides),
      references,
      reference_order: references.map(ref => ref.version_id),
      parameters,
    };
  }
  if (request.kind === "audio") {
    return { ...base, kind: "audio", speech_options: copy(request.speech_options), subject_node_id: request.subject_node_id, references, parameters };
  }
  // Image: an edit round's first input is the node's own base image, not an extra reference.
  const mode: WorkflowMode = options.workflowMode || request.mode || current?.mode || "text_to_image";
  const baseImage = mode === "edit" ? references.find(ref => ref.node_id === nodeId) : undefined;
  const extra = references.filter(ref => ref !== baseImage);
  if (request.negative_prompt !== undefined) parameters.negative_prompt = request.negative_prompt;
  return {
    ...base,
    mode,
    ...(request.provider === "openai" ? { model: request.model, quality: request.quality } : {}),
    references: extra,
    reference_order: references.map(ref => ref.version_id),
    mask_version_id: request.mask_version_id || undefined,
    edit_base_version_id: baseImage?.version_id,
    use_current_image: mode === "edit" ? true : mode === "reference" ? false : current?.use_current_image,
    parameters,
  };
}

export type RoundChange = { key: string; label: string };
/** What changed from the previous round (only fields the user controls). */
export function roundChanges(previous: GenerationJob | undefined, job: GenerationJob): RoundChange[] {
  if (!previous) return [];
  const a = snapshotOf(previous), b = snapshotOf(job), out: RoundChange[] = [];
  const add = (key: string, label: string, x: unknown, y: unknown) => { if (JSON.stringify(x ?? null) !== JSON.stringify(y ?? null)) out.push({ key, label }); };
  add("workflow", "工作流", a.workflow_id, b.workflow_id);
  add("prompt", "描述", a.prompt, b.prompt);
  add("negative", "负面描述", a.negative_prompt, b.negative_prompt);
  add("size", "尺寸", [a.parameters?.width, a.parameters?.height], [b.parameters?.width, b.parameters?.height]);
  add("steps", "步数", a.parameters?.steps, b.parameters?.steps);
  add("cfg", "CFG", a.parameters?.cfg, b.parameters?.cfg);
  add("seed", "种子", a.parameters?.seed, b.parameters?.seed);
  add("refs", "参考", (a.references || []).map(r => r.version_id + (r.role || "")), (b.references || []).map(r => r.version_id + (r.role || "")));
  if (b.kind === "video") {
    add("mode", "视频模式", a.video_mode, b.video_mode);
    add("duration", "时长", a.duration, b.duration);
    add("engine", "引擎", a.video_options?.engine, b.video_options?.engine);
  }
  return out;
}

/** The previous prompt is a prefix: return the appended tail so the UI can mark it. */
export function appendedTail(previous: string | undefined, prompt: string) {
  return previous && prompt.startsWith(previous) && prompt.length > previous.length ? prompt.slice(previous.length) : "";
}
