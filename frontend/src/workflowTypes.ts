export type WorkflowMode = "text_to_image" | "reference" | "edit";
export type WorkflowBinding = { node_id: string; input_name: string };
export type WorkflowBindings = {
  prompt: WorkflowBinding[];
  negative_prompt: WorkflowBinding[];
  seed: WorkflowBinding[];
  width: WorkflowBinding[];
  height: WorkflowBinding[];
  steps: WorkflowBinding[];
  cfg: WorkflowBinding[];
  denoise: WorkflowBinding[];
  images: WorkflowBinding[];
  mask: WorkflowBinding | null;
};
export type WorkflowIssue = { code: string; message: string; node_id?: string; input_name?: string };
export type WorkflowReport = {
  valid: boolean;
  online: boolean;
  checked_at: string;
  errors: WorkflowIssue[];
  warnings: WorkflowIssue[];
  output_nodes: string[];
};
export type WorkflowGraph = Record<string, {
  class_type: string;
  inputs: Record<string, unknown>;
  _meta?: { title?: string };
}>;
export type Workflow = {
  provider?: "openai" | "comfyui";
  id: string;
  name: string;
  description: string;
  mode: WorkflowMode;
  api_graph: WorkflowGraph;
  bindings: WorkflowBindings;
  capabilities: {
    reference_mapping?: "numbered" | "unsupported";
    min_images: number;
    max_images: number;
    requires_mask: boolean;
    supports_mask: boolean;
    reference_kind: "none" | "image_conditioning" | "img2img";
  };
  defaults: Record<string, number | string>;
  output_nodes: string[];
  revision: number;
  builtin: boolean;
  read_only: boolean;
  created_at: string;
  updated_at: string;
  validation: WorkflowReport | null;
  ready: boolean | null;
};
export const workflowModeNames: Record<WorkflowMode, string> = {
  text_to_image: "文生图",
  reference: "参考生图",
  edit: "图像编辑",
};
