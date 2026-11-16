export type Step = "welcome" | "comfy" | "models" | "verify" | "identity";
export type Job = {
  id: string;
  kind: string;
  status: string;
  progress: number;
  message: string;
  error?: string;
  error_code?: string | null;
  log_tail?: string;
  result?: { conflicts?: string[]; unavailable?: string[] };
  completed_bytes?: number;
  total_bytes?: number;
};
export type ModelFile = {
  path: string;
  size: number;
  packs: string[];
  status: string;
  source?: string | null;
  download_path?: string;
};
export type ModelScan = {
  files: ModelFile[];
  free_bytes: number;
  copy_bytes: number;
  import_disk_full: boolean;
  reusable_roots: { path: string; matched: number; total: number }[];
};
export type SetupState = {
  step: Step;
  completed: boolean;
  packs: string[];
  models_root: string;
  import_sources: string[];
  job: Job | null;
  busy: boolean;
  policy_version: string;
  default_comfy_path: string;
  default_models_root: string;
  platform_supported: boolean;
  library_has_projects: boolean;
  existing_library_installation?: boolean;
  validation: null | {
    verified: number;
    total: number;
    missing: ModelFile[];
    files: ModelFile[];
  };
  share_scan: null | {
    checked_at: string;
    files: { path: string; status: string; remote_path?: string | null }[];
  };
  consent: null | { privacy: string; manual: string };
};
export type Catalog = {
  packs: {
    id: string;
    name: string;
    description: string;
    bytes: number;
    count: number;
  }[];
  files: ModelFile[];
  total_bytes: number;
  share: { url: string; passcode: string };
  mirrors?: { id: string; name: string; url: string }[];
};
export type Installation = {
  path: string;
  name: string;
  comfy_path: string;
  python_path: string;
  kind: string;
};
export type ComfyState = {
  status: string;
  installation: Installation | null;
  installation_path: string | null;
  base_url: string;
  port: number;
  managed: boolean;
  can_start: boolean;
  can_stop: boolean;
  error?: string;
  queue?: { running: number; pending: number };
};
export type Readiness = {
  ready: boolean;
  comfy: ComfyState;
  packs: { pack: string; ready: boolean; missing_nodes: string[] }[];
};
