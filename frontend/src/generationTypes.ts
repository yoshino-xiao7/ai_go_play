import type { WorkflowMode } from "./workflowTypes";

export type ImageHistoryItem = {
  candidate?: boolean;
  version_id: string;
  job_id?: string;
  created_at?: string;
};

export type ImageReference = {
  fit?: "contain" | "cover";
  crop?: {x:number;y:number;width:number;height:number};
  purpose?: "general" | "identity" | "composition" | "motion" | "camera" | "voice";
  use_audio?: boolean;
  clip_start?: number;
  clip_end?: number | null;
  media_type?: "image" | "video" | "audio";
  role?: "reference" | "first_frame" | "last_frame" | "voice" | "emotion" | "video" | "audio";
  id?: string;
  description?: string;
  use_description?: boolean;
  source_missing?: boolean;
  latest_version_id?: string;
  version_id: string;
  node_id?: string;
  title: string;
  source: "base" | "connection" | "mention";
  edge_id?: string;
};

export type GenerationDraft = {
  lip_sync_options?: LipSyncOptions;
  video_options?: VideoOptions;
  enhance_options?: VideoEnhanceOptions;
  model?: string;
  quality?: string;
  kind?: "video" | "audio";
  speech_options?: SpeechOptions;
  subject_node_id?: string;
  video_mode?: "text" | "frames" | "reference";
  duration?: number;
  frame_count?: number;
  h3_guides?: H3Guide[];
  audio?: boolean;
  edit_base_version_id?: string;
  prompt_parts?: PromptPart[];
  workflow_drafts?: Record<string, Record<string, number | string>>;
  mode: WorkflowMode;
  prompt: string;
  workflow_id?: string;
  workflow_import_warning?: string;
  references: ImageReference[];
  reference_order?: string[];
  excluded_edge_ids?: string[];
  mask_version_id?: string;
  parameters: Record<string, number | string>;
  last_job_id?: string;
  pending_request_id?: string;
  use_current_image?: boolean;
  pending_submission?: GenerationRequest;
};

export type GenerationRequest = {
  lip_sync_options?: LipSyncOptions;
  video_options?: VideoOptions;
  enhance_options?: VideoEnhanceOptions;
  provider?: "openai";
  model?: string;
  quality?: string;
  kind?: "video" | "audio";
  speech_options?: SpeechOptions;
  subject_node_id?: string;
  video_mode?: "text" | "frames" | "reference";
  duration?: number;
  frame_count?: number;
  h3_guides?: H3Guide[];
  audio?: boolean;
  prompt_parts?: PromptPart[];
  result_policy?: "review" | "replace";
  project_id: string;
  source_node_id: string;
  workflow_id: string;
  mode?: WorkflowMode;
  prompt: string;
  negative_prompt?: string;
  references: (Pick<ImageReference, "id" | "description" | "use_description" | "version_id" | "node_id" | "edge_id" | "role" | "media_type"> & Partial<Pick<ImageReference, "title" | "source">>)[];
  mask_version_id?: string;
  parameters: Record<string, number | string>;
  placement: { x: number; y: number };
  request_id: string;
};

export type VideoEngine = "native"|"director"|"turbo";
export type VideoOptions = {engine?:VideoEngine;sampler?:"res_multistep"|"euler";scheduler?:"simple"|"beta"|"normal";ref_image_size?:"match"|"1024"|"1280"|"1536"|"max"};
export const VIDEO_INTERPOLATE_WORKFLOW = "builtin-video-interpolate-local";
export const VIDEO_UPSCALE_WORKFLOW = "builtin-video-upscale-local";
export type VideoEnhanceWorkflow = typeof VIDEO_INTERPOLATE_WORKFLOW | typeof VIDEO_UPSCALE_WORKFLOW;
export const isVideoEnhanceWorkflow = (id?: string): id is VideoEnhanceWorkflow => id === VIDEO_INTERPOLATE_WORKFLOW || id === VIDEO_UPSCALE_WORKFLOW;
export type VideoEnhanceMethod = "rife" | "hold" | "anime6b" | "remacri";
export type VideoEnhanceOptions = {method?: VideoEnhanceMethod; fps?: number; width?: number; height?: number; cuts?: number[]};
export type H3Guide = {
  id?: string;
  title?: string;
  version_id: string;
  media_type: "image" | "video" | "audio";
  frame_idx: number;
  use_audio?: boolean;
  clip_start?: number;
  clip_end?: number | null;
};
export type LipSyncOptions = {audio_offset?:number;video_start?:number;duration?:number|null;face_mode?:"auto"|"manual";face_box?:number[]|null};

export type PromptPart = { type: "text"; text: string } | { type: "reference"; reference_id: string };

export type GenerationJob = {
  id: string;
  status:
    | "pending"
    | "submitting"
    | "queued"
    | "running"
    | "collecting"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "unknown";
  project_id: string;
  source_node_id?: string;
  prompt_id?: string;
  error?:
    | string
    | { code?: string; message?: string; details?: unknown; phase?: string }
    | null;
  progress?: number | null;
  execution_progress?: {
    source: "comfyui"; connected: boolean; node_id?: string; node_type?: string;
    label?: string; value?: number; max?: number; updated_at?: string;
  } | null;
  message?: string | null;
  can_cancel?: boolean;
  can_retry?: boolean;
  request?: Record<string, unknown>;
  outputs: { asset_id: string; version_id: string; node_id: string | null }[];
  created_at: string;
  updated_at: string;
};

export const activeGenerationStates = new Set([
  "pending",
  "submitting",
  "queued",
  "running",
  "collecting",
  "unknown",
]);

export const generationStateLabels: Record<GenerationJob["status"], string> = {
  pending: "等待调度",
  submitting: "正在提交",
  queued: "排队中",
  running: "正在生成",
  collecting: "正在保存结果",
  succeeded: "生成完成",
  failed: "生成失败",
  cancelled: "已取消",
  unknown: "提交状态待核对",
};

export type SpeechOptions={language:string;speed:number;emotion:string;intensity:number;use_emo_text?:boolean;emo_text?:string;pronunciation?:string;interval_silence?:number;quality?:"standard"|"studio";temperature?:number};
