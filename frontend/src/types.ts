import type { Edge, Node, Viewport } from "@xyflow/react";

export type MediaKind = "image" | "video" | "audio";
export type Project = {
  id: string;
  name: string;
  aspect_ratio: "free" | "16:9" | "9:16";
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  revision: number;
  cover_version_id: string | null;
};

export type AssetVersion = {
  id: string;
  asset_id: string;
  filename: string;
  size: number;
  width: number | null;
  height: number | null;
  duration: number | null;
  mime: string;
  hash: string;
  missing: boolean;
  preview_status: "pending" | "ready" | "failed";
  path: string;
  created_at?: string;
  type?: MediaKind;
};

export type Asset = {
  id: string;
  name: string;
  type: MediaKind;
  tags: string[];
  source: string;
  created_at: string;
  deleted_at: string | null;
  current_version_id: string;
  imported_version_id?: string;
  version_count: number;
  version: AssetVersion;
  versions?: AssetVersion[];
  references?: { id: string; name: string; deleted_at?: string | null }[];
  subject_references?: { id: string; name: string; description: string; version_id: string }[];
};

export type CanvasData = {
  revision: number;
  nodes: Node[];
  edges: Edge[];
  viewport: Viewport;
};
export type AssetPage = { items: Asset[]; total: number };
export type Task = {
  id: string;
  type?: string;
  kind?: string;
  status: string;
  error?: string | null;
  created_at: string;
  updated_at?: string;
  asset_id?: string;
  version_id?: string;
  progress?: number;
  message?: string;
  requires_file?: boolean;
  can_retry?: boolean;
  filename?: string;
};
export type StorageInfo = {
  root: string;
  size_bytes: number;
  free_bytes: number;
  ffmpeg: string | null;
  ffprobe: string | null;
  migration?: {
    status: string;
    target: string;
    error?: string;
    progress?: number;
  } | null;
};
