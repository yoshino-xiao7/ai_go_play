import type { ProductionRender } from "./productionTypes";

export type TimelineTrackKind = "video" | "audio" | "text";
export type TimelineTrack = { id: string; name: string; type: TimelineTrackKind; order: number; muted: boolean; locked: boolean };
export type TimelineTransform = { x: number; y: number; scale: number; opacity: number };
export type TimelineTextStyle = { font_size: number; color: string; background_color: string; align: "left" | "center" | "right" };
export type TimelineClip = {
  id: string; track_id: string; start: number; duration: number; trim_start: number; trim_end?: number;
  name?: string; muted?: boolean; locked?: boolean; stale?: boolean; latest_version_id?: string | null;
  audio_preset?: "none" | "dialogue" | "phone" | "narration";
  asset_version_id?: string | null; source_node_id?: string | null; text: string;
  transform: TimelineTransform; volume: number; fade_in: number; fade_out: number; text_style: TimelineTextStyle;
};
export type TimelineSettings = { width: number; height: number; fps: number; background_color: string; duration: number | null };
export type TimelineEdit = { settings: TimelineSettings; tracks: TimelineTrack[]; clips: TimelineClip[] };
export type TimelineDocument = TimelineEdit & { revision: number; total_duration: number; renders: ProductionRender[] };
export type TimelineDraft = TimelineEdit & { revision: number; saved_at: number };
export const defaultTimelineSettings: TimelineSettings = { width: 1280, height: 720, fps: 24, background_color: "#000000", duration: null };
export const timelineDuration = (edit: TimelineEdit) => edit.settings.duration ?? Math.max(0, ...edit.clips.map(clip => clip.start + clip.duration));
export const timelineTime = (seconds: number) => `${Math.floor(Math.max(0, seconds) / 60).toString().padStart(2, "0")}:${(Math.max(0, seconds) % 60).toFixed(2).padStart(5, "0")}`;
export const clipGain = (clip: TimelineClip, local: number) => Math.min(1, clip.fade_in > 0 ? Math.max(0, local / clip.fade_in) : 1, clip.fade_out > 0 ? Math.max(0, (clip.duration - local) / clip.fade_out) : 1);
