export type ProductionSettings = {
  width: number;
  height: number;
  fps: number;
  background_audio_version_id?: string | null;
  background_volume: number;
};

export type ProductionShot = {
  id: string;
  order: number;
  title: string;
  scene: string;
  characters: string[];
  dialogue: string;
  speaker: string;
  duration: number;
  video_version_id?: string | null;
  audio_version_id?: string | null;
  audio_duration?: number | null;
  video_node_id?: string | null;
  audio_node_id?: string | null;
  trim_start: number;
  audio_offset: number;
  subtitle_start?: number | null;
  subtitle_end?: number | null;
  video_volume: number;
  audio_volume: number;
  status: "draft" | "ready" | "approved";
  notes: string;
  stale?: boolean;
  stale_fields?: string[];
  latest_video_version_id?: string | null;
  latest_audio_version_id?: string | null;
};

export type ProductionRender = {
  id: string;
  project_id: string;
  status: "pending" | "running" | "succeeded" | "failed";
  progress?: number;
  message?: string;
  error?: string | { message?: string } | null;
  output_version_id?: string | null;
  output_asset_id?: string | null;
  output_node_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type ProductionDocument = {
  revision: number;
  settings: ProductionSettings;
  shots: ProductionShot[];
  renders: ProductionRender[];
  total_duration?: number;
};
