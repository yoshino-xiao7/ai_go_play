import {GenerationProgress} from "./GenerationProgress";
import {ReferenceTile,useReferencePreview} from "./ReferenceMedia";
import StudioSelect from "./StudioSelect";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertCircle,
  ArrowUp,
  ArrowUpRight,
  AtSign,
  Brush,
  Camera,
  Check,
  CircleStop,
  ChevronDown,
  LoaderCircle,
  Maximize2,
  Palette,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Sparkles,
  Sun,
  Upload,
  X,
} from "lucide-react";
import { ApiError, api, mediaUrl, uploadAsset } from "./api";
import type { AssetPage } from "./types";
import type { Workflow, WorkflowMode } from "./workflowTypes";
import { workflowModeNames } from "./workflowTypes";
import type {
  GenerationDraft,
  GenerationJob,
  GenerationRequest,
  ImageReference,
} from "./generationTypes";
import {
  activeGenerationStates,
  generationStateLabels,
} from "./generationTypes";
import MaskEditor from "./MaskEditor";
import PromptEditor from "./PromptEditor";
import type { PromptEditorHandle } from "./PromptEditor";
import type { SubjectPage } from "./subjectTypes";
import { promptParts, referenceId } from "./referenceModel";
import OpenAIImageControls from "./OpenAIImageControls";
import { useOpenAIImages } from "./openaiImages";

type Props = {
  projectId: string;
  nodeId: string;
  title: string;
  versionId?: string;
  draft?: GenerationDraft;
  connections: ImageReference[];
  unresolvedConnections?: number;
  onConfirmConnections?: (role:"reference"|"relation")=>void;
  sourceVersions?: Record<string,string>;
  sourceImages?: Record<string,string[]>;
  sourceDescriptions?: Record<string,string>;
  onUpdateReference?: (reference:ImageReference)=>void;
  canvasReferences?: ImageReference[];
  locked?: boolean;
  position: { x: number; y: number };
  onChange: (draft: GenerationDraft) => void;
  onBeginEdit: () => void;
  onRemoveConnections: (edgeIds: string[]) => void;
  onBeforeSubmit: () => Promise<void>;
  onReveal: (nodeId: string) => void;
  onAssetsChange: () => void;
};

export const defaultGenerationDraft = (hasImage = false): GenerationDraft => ({
  mode: hasImage ? "edit" : "text_to_image",
  prompt: "",
  references: [],
  parameters: {},
  use_current_image: hasImage,
});

const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
const emptyReferences: ImageReference[] = [];
const ratios = [
  { label: "1:1", width: 1, height: 1 },
  { label: "16:9", width: 16, height: 9 },
  { label: "9:16", width: 9, height: 16 },
  { label: "4:3", width: 4, height: 3 },
  { label: "3:4", width: 3, height: 4 },
];
const creativePresets = {
  camera: [{ label: "人物特写", text: "人物面部特写，聚焦眼神与表情" }, { label: "半身中景", text: "半身中景，自然姿态，清晰的人物轮廓" }, { label: "环境远景", text: "环境远景，完整呈现人物与场景的空间关系" }, { label: "双人同框", text: "双人同框，平衡构图，人物间有自然的互动" }, { label: "低机位", text: "低机位仰拍，增强画面的纵深与张力" }],
  style: [{ label: "日系动画", text: "日系二次元动画风格，干净线稿，赛璐璐上色" }, { label: "电影分镜", text: "动画电影分镜，细腻的背景绘制，叙事性的构图" }, { label: "清透水彩", text: "清透水彩插画，柔和晕染，轻盈的笔触" }, { label: "黑白漫画", text: "黑白漫画，鲜明的线条，细致网点与明暗对比" }],
  light: [{ label: "窗边晨光", text: "柔和晨光透过窗户，明亮通透，自然的光影层次" }, { label: "暖色夕阳", text: "暖色夕阳，柔和逆光，发丝边缘有金色轮廓光" }, { label: "月色夜景", text: "清冷月色，蓝色夜景，细腻而安静的氛围" }, { label: "柔光棚拍", text: "均匀柔光，主体清晰，柔和阴影" }],
};
function promptMentions(prompt: string, references: ImageReference[]) {
  const ordered = [...references].sort((a, b) => b.title.length - a.title.length);
  const matches: { start: number; end: number; reference: ImageReference }[] = [];
  for (let cursor = 0; cursor < prompt.length; cursor++) {
    if (prompt[cursor] !== "@") continue;
    const reference = ordered.find(item => item.title && prompt.startsWith(`@${item.title}`, cursor));
    if (reference) { matches.push({ start: cursor, end: cursor + reference.title.length + 1, reference }); cursor += reference.title.length; }
  }
  return matches;
}

export default function GenerationComposer({
  projectId,
  nodeId,
  title,
  versionId,
  draft: incomingDraft,
  connections,
  unresolvedConnections=0, onConfirmConnections, sourceVersions={}, sourceImages={}, sourceDescriptions={}, onUpdateReference,
  canvasReferences = emptyReferences,
  locked,
  position,
  onChange,
  onBeginEdit,
  onRemoveConnections,
  onBeforeSubmit,
  onReveal,
  onAssetsChange,
}: Props) {
  const draft = incomingDraft || defaultGenerationDraft(!!versionId);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflowLoading, setWorkflowLoading] = useState(true);
  const [workflowError, setWorkflowError] = useState("");
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [jobAction, setJobAction] = useState(false);
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const [showParameters, setShowParameters] = useState(false);
  const [showEffective, setShowEffective] = useState(false);
  const [showMaskTools, setShowMaskTools] = useState(false);
  const [showJobDetails, setShowJobDetails] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerScope, setPickerScope] = useState<"canvas" | "all" | "subjects">("canvas");
  const [pickerAssets, setPickerAssets] = useState<ImageReference[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerIndex, setPickerIndex] = useState(0);
  const [maskEditor, setMaskEditor] = useState(false);
  const [maskUploading, setMaskUploading] = useState(false);
  const textarea = useRef<PromptEditorHandle>(null);
  const [sizeOpen, setSizeOpen] = useState(false);
  const [presetOpen, setPresetOpen] = useState<"camera" | "style" | "light" | null>(null);
  const {setReferencePreview,hoverReference,openReference,renderReferencePreview}=useReferencePreview();
  const composerRoot = useRef<HTMLDivElement>(null);
  const [expanded,setExpanded]=useState(false);
  const [collapsed,setCollapsed]=useState(false);
  const [updateCandidate,setUpdateCandidate]=useState<ImageReference|null>(null);
  const [missingVersions,setMissingVersions]=useState<string[]>([]);
  const knownReferences = useRef(new Map<string, ImageReference>());
  const maskInput = useRef<HTMLInputElement>(null);
  const mentionRange = useRef<{ start: number; end: number } | null>(null);
  const composing = useRef(false);
  const alive = useRef(true);
  const pickerSequence = useRef(0);
  const jobSequence = useRef(0);
  const activeJob = useRef<GenerationJob | null>(null);

  const updateDraft = useCallback(
    (patch: Partial<GenerationDraft>) => {
      const next = { ...draftRef.current, ...patch };
      if (patch.prompt!==undefined || patch.references!==undefined) next.prompt_parts=promptParts(next.prompt,next.references);
      draftRef.current = next;
      onChange(next);
    },
    [onChange],
  );

  const refreshWorkflows = useCallback(async () => {
    try {
      const response = await api<{ items: Workflow[] }>("/api/workflows");
      if (!alive.current) return;
      setWorkflows(response.items);
      setWorkflowError("");
    } catch (caught) {
      if (alive.current) setWorkflowError(messageOf(caught));
    } finally {
      if (alive.current) setWorkflowLoading(false);
    }
  }, []);

  const refreshJob = useCallback(async () => {
    const sequence = ++jobSequence.current;
    try {
      const response = await api<{ items: GenerationJob[] }>(
        `/api/generations?project_id=${encodeURIComponent(projectId)}`,
      );
      if (!alive.current || sequence !== jobSequence.current) return;
      const candidates = response.items
        .filter((item) => item.source_node_id === nodeId)
        .sort((first, second) =>
          second.created_at.localeCompare(first.created_at),
        );
      const next = candidates[0] || null;
      activeJob.current = next;
      setJob(next);
    } catch (caught) {
      if (alive.current) setError(messageOf(caught));
    }
  }, [projectId, nodeId]);

  useEffect(() => {
    alive.current = true;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    void refreshWorkflows();
    const poll = async () => {
      await refreshJob();
      if (disposed) return;
      const active =
        activeJob.current &&
        activeGenerationStates.has(activeJob.current.status);
      timer = setTimeout(() => void poll(), active ? 1200 : 6000);
    };
    void poll();
    const listener = (event: Event) => {
      const payload = (event as CustomEvent).detail || {};
      const type = String(payload.type || "");
      if (type.startsWith("workflow.")) void refreshWorkflows();
      if (
        type === "generation.updated" &&
        payload.data?.project_id === projectId
      )
        void refreshJob();
    };
    window.addEventListener("manju:event", listener);
    window.addEventListener("manju:reconnected", refreshJob);
    return () => {
      disposed = true;
      alive.current = false;
      clearTimeout(timer);
      window.removeEventListener("manju:event", listener);
      window.removeEventListener("manju:reconnected", refreshJob);
    };
  }, [projectId, refreshJob, refreshWorkflows]);

  const availableWorkflows = workflows.filter(
    (workflow) => workflow.mode === draft.mode,
  );
  const selectedWorkflow =
    availableWorkflows.find((workflow) => workflow.id === draft.workflow_id) ||
    (!draft.workflow_id
      ? availableWorkflows.find((workflow) => workflow.ready !== false) ||
        availableWorkflows[0]
      : undefined);
  const isOpenAI = selectedWorkflow?.provider === "openai";
  const workflowForMode = (mode: GenerationDraft["mode"]) => {
    if (isOpenAI) return `builtin-openai-${mode}`;
    if (selectedWorkflow?.id.startsWith("builtin-minimax-h3-image-")) {
      return workflows.find(workflow => workflow.id === `builtin-minimax-h3-image-${mode}`)?.id;
    }
    return undefined;
  };
  const openaiOptions = {
    model: draft.model || "gpt-image-2.6-flare",
    quality: draft.quality || "high",
    width: Number(draft.parameters.width ?? 1024),
    height: Number(draft.parameters.height ?? 1024),
  };
  const openai = useOpenAIImages(isOpenAI, openaiOptions);
  const references = useMemo(() => {
    const refs: ImageReference[] = [];
    if (
      versionId &&
      (draft.mode === "edit" ||
        (draft.mode === "reference" && draft.use_current_image !== false))
    )
      refs.push({
        version_id: versionId,
        node_id: nodeId,
        title,
        source: "base",
      });
    refs.push(
      ...connections.filter(
        (reference) =>
          !draft.excluded_edge_ids?.includes(reference.edge_id || ""),
      ),
      ...(draft.references || []),
    );
    const unique = refs.filter(
      (reference, index) =>
        refs.findIndex((item) => item.version_id === reference.version_id) ===
        index,
    ).map(reference => ({ ...reference }));
    const titles = new Set<string>();
    unique.forEach(reference => {
      const original = draft.references?.find(item => item.version_id === reference.version_id)?.title || reference.title;
      let title = original, suffix = 2;
      while (titles.has(title)) title = `${original} · ${suffix++}`;
      reference.title = title;
      titles.add(title);
    });
    const order = draft.reference_order || [];
    unique.sort((first, second) => {
      const firstIndex = order.indexOf(first.version_id);
      const secondIndex = order.indexOf(second.version_id);
      return (
        (firstIndex < 0 ? order.length : firstIndex) -
        (secondIndex < 0 ? order.length : secondIndex)
      );
    });
    if (draft.mode === "edit" && versionId) {
      const baseIndex = unique.findIndex(
        (reference) => reference.version_id === versionId,
      );
      if (baseIndex > 0) unique.unshift(...unique.splice(baseIndex, 1));
    }
    return unique;
  }, [
    draft.mode,
    draft.references,
    draft.reference_order,
    draft.excluded_edge_ids,
    draft.use_current_image,
    connections,
    versionId,
    nodeId,
    title,
  ]);
  references.forEach(reference => knownReferences.current.set(reference.title, { ...reference }));

  useEffect(() => {
    if (!pickerOpen) return;
    if (pickerScope === "canvas") {
      setPickerAssets(canvasReferences.filter(reference => reference.title.toLocaleLowerCase().includes(pickerQuery.trim().toLocaleLowerCase())));
      setPickerLoading(false);
      setPickerIndex(0);
      return;
    }
    const sequence = ++pickerSequence.current;
    const controller = new AbortController();
    setPickerLoading(true);
    setPickerAssets([]);
    setPickerIndex(0);
    const timer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          type: "image",
          limit: "24",
          search: pickerQuery,
        });
        const candidates = pickerScope === "subjects"
          ? (await api<SubjectPage>(`/api/subjects?${new URLSearchParams({ search: pickerQuery, limit: "40" })}`, { signal: controller.signal })).items.flatMap(subject => (subject.images?.length ? subject.images : [subject.version]).flatMap((version, index) => !version || version.missing ? [] : [{ version_id: version.id, title: index === 0 ? subject.name : `${subject.name} · 参考${index + 1}`, description:subject.description, use_description:true, source: "mention" as const }]))
          : (await api<AssetPage>(`/api/assets?${params}`, { signal: controller.signal })).items.filter(asset => !asset.version?.missing).map(asset => ({ version_id: asset.current_version_id, title: asset.name, source: "mention" as const }));
        if (sequence !== pickerSequence.current || !alive.current) return;
        setPickerAssets(candidates);
        setPickerIndex(0);
      } catch (caught) {
        if (!controller.signal.aborted && alive.current)
          setError(messageOf(caught));
      } finally {
        if (sequence === pickerSequence.current && alive.current)
          setPickerLoading(false);
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [pickerOpen, pickerScope, pickerQuery, projectId, canvasReferences]);

  const selectReference = (candidate: ImageReference) => {
    if (locked || submitting || draftRef.current.pending_submission || pickerLoading) return;
    const existing = references.find(item => item.version_id === candidate.version_id);
    let reference = existing ? { ...existing, source: "mention" as const } : { ...candidate };
    if (!existing) {
      let title = candidate.title, suffix = 2;
      while (knownReferences.current.has(title) && knownReferences.current.get(title)?.version_id !== candidate.version_id) title = `${candidate.title} · ${suffix++}`;
      reference = { ...reference, id:referenceId(reference), title };
    }
    knownReferences.current.set(reference.title, reference);
    onBeginEdit();
    const current = draftRef.current;
    const nextRefs = current.references || [];
    const range = mentionRange.current;
    let prompt = current.prompt;
    if (range)
      prompt = `${prompt.slice(0, range.start)}@${reference.title} ${prompt.slice(range.end)}`;
    updateDraft({
      prompt,
      ...(current.mode === "text_to_image" ? { mode: "reference" as const, workflow_id: workflowForMode("reference"), workflow_import_warning: undefined, use_current_image: false } : {}),
      references: nextRefs.some(
        (item) => item.version_id === reference.version_id,
      )
        ? nextRefs
        : [...nextRefs, reference],
    });
    setPickerOpen(false);
    mentionRange.current = null;
    requestAnimationFrame(() => {
      textarea.current?.focus();
      if (range) textarea.current?.setSelection(range.start + reference.title.length + 2);
    });
  };

  const removeReference = (reference: ImageReference) => {
    if (locked || submitting || draftRef.current.pending_submission) return;
    if (reference.source === "base" && draft.mode === "edit" && versionId)
      return;
    onBeginEdit();
    if (reference.source === "base") updateDraft({ use_current_image: false });
    const linked = connections
      .filter(
        (item) => item.version_id === reference.version_id && item.edge_id,
      )
      .map((item) => item.edge_id!);
    if (linked.length) onRemoveConnections(linked);
    let prompt = draftRef.current.prompt;
    const matches = promptMentions(prompt, [...knownReferences.current.values()]).filter(item => item.reference.version_id === reference.version_id);
    for (const match of matches.reverse()) prompt = prompt.slice(0, match.start) + prompt.slice(match.end);
    updateDraft({
      references: (draftRef.current.references || []).filter(
        (item) => item.version_id !== reference.version_id,
      ),
      prompt,
    });
  };

  const reorderReference = (index: number, direction: number) => {
    const next = [...references];
    const target = index + direction;
    if (
      target < 0 ||
      target >= next.length ||
      (draft.mode === "edit" && versionId && (index === 0 || target === 0))
    )
      return;
    [next[index], next[target]] = [next[target], next[index]];
    onBeginEdit();
    updateDraft({
      reference_order: next.map((reference) => reference.version_id),
    });
  };

  const capabilityError = useMemo(() => {
    if (unresolvedConnections) return "旧连线用途待确认。";
    if (references.some((ref,index)=>references.some((other,j)=>j!==index && other.title===ref.title && other.version_id!==ref.version_id))) return "存在同名引用，请移除后重新通过 @ 选择，避免主体对应错误。";
    if (missingVersions.length) return "参考图原件不可读取，请修复、替换或移除。";
    if (!selectedWorkflow)
      return workflowLoading
        ? "正在读取工作流…"
        : draft.workflow_id
          ? `${draft.workflow_import_warning || "原工作流不可用，请选择或导入工作流。"}（${draft.workflow_id}）`
          : "请先选择或维护一个可用工作流。";
    if (selectedWorkflow.ready === false)
      return (
        selectedWorkflow.provider === "openai" ? "请先在工作流中检查 OpenAI 密钥与连接。" :
        selectedWorkflow.validation?.errors
          .map((issue) => issue.message)
          .join("；") || "工作流校验未通过，请先在工作流库修复。"
      );
    const limits = selectedWorkflow.capabilities;
    if (promptParts(draft.prompt,references).some(part=>part.type==="reference") && limits.reference_mapping!=="numbered" && limits.reference_mapping!=="picture" && !selectedWorkflow.id.startsWith("builtin-qwen21-")) return "工作流未适配 @ 名称映射，请在工作流库配置。";
    if (references.length < limits.min_images)
      return `此工作流至少需要 ${limits.min_images} 张图片，当前有 ${references.length} 张。`;
    if (references.length > limits.max_images)
      return limits.max_images === 0
        ? "此工作流不接收图片引用，请切换参考生图或移除引用。"
        : `此工作流最多接收 ${limits.max_images} 张图片，当前有 ${references.length} 张，请移除多余引用。`;
    if (draft.mode === "edit" && !references.length)
      return "请添加一张编辑底图。";
    if (draft.mask_version_id && !limits.supports_mask)
      return "此工作流不支持蒙版，请移除蒙版或切换工作流。";
    if (limits.requires_mask && !draft.mask_version_id)
      return "此工作流需要蒙版，请绘制或上传需要修改的区域。";
    if (isOpenAI && openai.issue) return openai.issue;
    const seed = isOpenAI ? undefined : draft.parameters.seed;
    if (
      seed !== undefined &&
      (!Number.isSafeInteger(seed) || Number(seed) < -1)
    )
      return "种子须为 -1（随机）或 0 至 9007199254740991 的整数。";
    return "";
  }, [
    draft.mode,
    draft.mask_version_id,
    draft.workflow_id,
    draft.workflow_import_warning,
    draft.parameters.seed,
    references, draft.prompt, unresolvedConnections, missingVersions,
    selectedWorkflow,
    workflowLoading,
    isOpenAI, openai.issue,
  ]);
  const active = !!job && activeGenerationStates.has(job.status);
  const resultNodeId = job?.outputs[0]?.node_id;
  const pendingSubmission = draft.pending_submission;
  const disabledEditing = !!locked || submitting || !!pendingSubmission;
  const canSubmit =
    !locked &&
    !active &&
    job?.status !== "unknown" &&
    !submitting &&
    (!!pendingSubmission || (!!draft.prompt.trim() && !capabilityError));

  const changeMode = (mode: WorkflowMode) => {
    if (disabledEditing) return;
    onBeginEdit();
    updateDraft({ mode, workflow_id: workflowForMode(mode), workflow_import_warning: undefined, ...(mode !== "edit" ? {edit_base_version_id:undefined} : {}), ...(mode === "reference" ? { use_current_image: false } : {}) });
    setShowMaskTools(false);
    setError("");
  };
  useEffect(() => {
    const handler = (event: Event) => {
      const command = (event as CustomEvent).detail;
      if (command?.nodeId !== nodeId || disabledEditing) return;
      if (command.action === "parameters") { setShowParameters(value => !value); return; }
      if (command.action === "edit" || command.action === "reference") changeMode(command.action);
      if (command.action === "mask") { changeMode("edit"); setShowMaskTools(true); }
      requestAnimationFrame(() => textarea.current?.focus());
    };
    window.addEventListener("manju:composer-action", handler);
    return () => window.removeEventListener("manju:composer-action", handler);
  });
  const referenceSignature=references.map(ref=>ref.version_id).join("|");
  useEffect(()=>{
    let alive=true;
    const inspect=()=>void Promise.all(references.map(async ref=>{
      try {const response=await fetch(mediaUrl(ref.version_id,"original"),{method:"HEAD"});return response.ok?null:ref.version_id;} catch {return ref.version_id;}
    })).then(ids=>{if(alive)setMissingVersions(ids.filter((id):id is string=>!!id));});
    inspect();window.addEventListener("manju:reconnected",inspect);
    return ()=>{alive=false;window.removeEventListener("manju:reconnected",inspect);};
  },[referenceSignature]);
  useEffect(() => {
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !composerRoot.current?.contains(event.target) && !(event.target instanceof Element && event.target.closest(".studio-reference-picker-overlay"))) {
        setSizeOpen(false); setPresetOpen(null); setPickerOpen(false); setReferencePreview(null); mentionRange.current = null;
      }
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  useEffect(() => {
    const selector = sizeOpen ? ".studio-size-panel" : showParameters ? ".generation-settings" : showMaskTools ? ".generation-mask-row" : presetOpen ? ".studio-presets" : "";
    if (!selector) return;
    const frame = requestAnimationFrame(() => {
      const panel = composerRoot.current;
      const section = panel?.querySelector<HTMLElement>(selector);
      const footer = panel?.querySelector<HTMLElement>(".generation-footer");
      if (!panel || !section || !footer) return;
      const area = panel.getBoundingClientRect(), box = section.getBoundingClientRect();
      if (box.bottom > footer.getBoundingClientRect().top || box.top < area.top)
        panel.scrollTo({ top: panel.scrollTop + box.top - area.top - 12, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [sizeOpen, showParameters, showMaskTools, presetOpen]);
  const openPicker = () => {
    mentionRange.current = null;
    setPickerQuery(""); setPickerOpen(value => !value); setPresetOpen(null); setSizeOpen(false);
  };

  const changePrompt = (value: string, caret: number) => {
    if (disabledEditing) return;
    const current = draftRef.current;
    const known = [...knownReferences.current.values()];
    const previous = new Set(promptMentions(current.prompt, known).map(match => match.reference.version_id));
    const nextMentions = promptMentions(value, known);
    const nextVersions = new Set(nextMentions.map(match => match.reference.version_id));
    const nextReferences = (current.references || []).filter(reference => reference.source==="connection" || !previous.has(reference.version_id) || nextVersions.has(reference.version_id));
    for (const match of nextMentions) {
      const reference = match.reference;
      if (!nextReferences.some(item => item.version_id === reference.version_id) && !connections.some(item => item.version_id === reference.version_id) && !(reference.source === "base" && versionId === reference.version_id))
        nextReferences.push({ ...reference, source: "mention", edge_id: undefined });
    }
    updateDraft({ prompt: value, references: nextReferences });
    const match = value.slice(0, caret).match(/@([^\s@]*)$/u);
    const resolved = nextMentions.some(item => item.end === caret);
    if (match && !resolved) { mentionRange.current = { start: caret - match[1].length - 1, end: caret }; setPickerQuery(match[1]); setPickerOpen(true); setPresetOpen(null); setSizeOpen(false); }
    else if (mentionRange.current || resolved) { mentionRange.current = null; setPickerOpen(false); }
  };
  const currentWidth = Number(draft.parameters.width ?? selectedWorkflow?.defaults.width ?? 1024);
  const currentHeight = Number(draft.parameters.height ?? selectedWorkflow?.defaults.height ?? 1024);
  const currentRatio = ratios.find(ratio => Math.abs(currentWidth / currentHeight - ratio.width / ratio.height) < 0.01);
  const currentLongEdge = Math.max(currentWidth, currentHeight);
  const canSetSize = !!selectedWorkflow?.bindings.width.length && !!selectedWorkflow?.bindings.height.length;
  const setSize = (ratio = currentRatio || ratios[0], edge = [512, 1024, 2048].includes(currentLongEdge) ? currentLongEdge : 1024) => {
    if (!canSetSize || disabledEditing) return;
    const longest = Math.max(ratio.width, ratio.height);
    const width = Math.round(edge * ratio.width / longest / 32) * 32;
    const height = Math.round(edge * ratio.height / longest / 32) * 32;
    onBeginEdit();
    updateDraft({ parameters: { ...draftRef.current.parameters, width, height } });
  };
  const addPreset = (text: string) => {
    if (disabledEditing) return;
    const current = draftRef.current.prompt.trimEnd();
    onBeginEdit();
    const prompt = `${current}${current && !/[，。；、！？,;!?]$/u.test(current) ? "，" : ""}${text}`;
    updateDraft({ prompt }); setPresetOpen(null);
    requestAnimationFrame(() => { textarea.current?.focus(); textarea.current?.setSelection(prompt.length); });
  };

  /** The exact body POST /api/generations receives. “实际提交” shows this same object. */
  const buildRequest = (): GenerationRequest => ({
      project_id: projectId,
      ...(isOpenAI ? { provider: "openai" as const, model: openaiOptions.model, quality: openaiOptions.quality } : {}),
      source_node_id: nodeId,
      workflow_id: selectedWorkflow!.id,
      prompt: draft.prompt,
      prompt_parts:promptParts(draft.prompt,references),
      result_policy:"replace",
      negative_prompt: String(
        draft.parameters.negative_prompt ??
          selectedWorkflow!.defaults.negative_prompt ??
          "",
      ),
      references: references.map((reference) => ({
        id:referenceId(reference),title:reference.title,description:reference.description,use_description:reference.use_description,
        version_id: reference.version_id,
        node_id: reference.node_id,
      })),
      mask_version_id: draft.mask_version_id,
      parameters: {
        ...(isOpenAI ? { width: openaiOptions.width, height: openaiOptions.height } : {}),
        ...Object.fromEntries(
          Object.entries(draft.parameters).filter(([key]) =>
            ["seed", "width", "height", "steps", "cfg", "denoise"].includes(key) && !!selectedWorkflow!.bindings[key as "seed"|"width"|"height"|"steps"|"cfg"|"denoise"]?.length,
          ),
        ),
        ...(selectedWorkflow!.bindings.seed.length
          ? {
              seed:
                draft.parameters.seed ?? selectedWorkflow!.defaults.seed ?? -1,
            }
          : {}),
      },
      placement: position,
      request_id: crypto.randomUUID(),
  });
  const submit = async () => {
    if (!canSubmit || (!selectedWorkflow && !pendingSubmission)) return;
    setSubmitting(true);
    setError("");
    setPickerOpen(false); setSizeOpen(false); setPresetOpen(null); setReferencePreview(null); setShowEffective(false);
    const request: GenerationRequest = pendingSubmission || buildRequest();
    try {
      updateDraft({
        workflow_id: request.workflow_id,
        pending_submission: request,
        // A first result turns an empty card into an image card. Preserve the
        // input choice made before submission instead of adding that result.
        use_current_image: draft.use_current_image ?? !!versionId,
      });
      await onBeforeSubmit();
      const result = await api<GenerationJob>("/api/generations", {
        method: "POST",
        body: JSON.stringify(request),
      });
      if (!alive.current) return;
      jobSequence.current += 1;
      activeJob.current = result;
      setJob(result);
      // A refilled draft became a new round: keep the lineage locally, clear the refill marker.
      const refilled = draftRef.current.refill_of;
      updateDraft({ pending_submission: undefined, last_job_id: result.id, refill_of: undefined,
        ...(refilled ? { round_links: { ...(draftRef.current.round_links || {}), [result.id]: refilled.job_id } } : {}) });
    } catch (caught) {
      if (!alive.current) return;
      if (caught instanceof ApiError && caught.status < 500)
        updateDraft({ pending_submission: undefined });
      setError(messageOf(caught));
    } finally {
      if (alive.current) setSubmitting(false);
    }
  };

  const jobOperation = async (
    operation: "cancel" | "retry",
    interruptRunning = false,
  ) => {
    if (!job || jobAction) return;
    setJobAction(true);
    setError("");
    try {
      const next = await api<GenerationJob>(
        `/api/generations/${job.id}/${operation}`,
        {
          method: "POST",
          body: JSON.stringify(
            operation === "cancel"
              ? { interrupt_running: interruptRunning }
              : { request_id: crypto.randomUUID() },
          ),
        },
      );
      if (!alive.current) return;
      jobSequence.current += 1;
      activeJob.current = next;
      setJob(next);
      setConfirmCancellation(false);
      updateDraft({ last_job_id: next.id });
    } catch (caught) {
      if (alive.current) {
        if (
          caught instanceof ApiError &&
          (caught.detail as { code?: string })?.code ===
            "generation_interrupt_confirmation"
        )
          setConfirmCancellation(true);
        else setError(messageOf(caught));
      }
    } finally {
      if (alive.current) setJobAction(false);
    }
  };

  const uploadMask = async (file: File) => {
    setMaskUploading(true);
    setError("");
    try {
      const asset = await uploadAsset(file, { projectId });
      onBeginEdit();
      updateDraft({
        mask_version_id: asset.imported_version_id || asset.current_version_id,
      });
      onAssetsChange();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setMaskUploading(false);
    }
  };

  const parameterFields = [
    {
      key: "seed",
      label: "种子",
      min: -1,
      max: Number.MAX_SAFE_INTEGER,
      step: 1,
      fallback: -1,
    },
    {
      key: "width",
      label: "宽度",
      min: 64,
      max: 4096,
      step: 32,
      fallback: 1024,
    },
    {
      key: "height",
      label: "高度",
      min: 64,
      max: 4096,
      step: 32,
      fallback: 1024,
    },
    { key: "steps", label: "步数", min: 1, max: 1000, step: 1, fallback: 20 },
    { key: "cfg", label: "提示强度", min: 0, max: 100, step: 0.5, fallback: 7 },
    {
      key: "denoise",
      label: "重绘幅度",
      min: 0,
      max: 1,
      step: 0.05,
      fallback: 0.7,
    },
  ].filter((field) => {
    const binding =
      selectedWorkflow?.bindings[field.key as keyof Workflow["bindings"]];
    return Array.isArray(binding) && binding.length > 0;
  });
  const jobError =
    typeof job?.error === "string" ? job.error : job?.error?.message;
  // Preflight list for “实际提交”. Submission itself is still gated by capabilityError / canSubmit.
  const limits = selectedWorkflow?.capabilities;
  const seedValue = draft.parameters.seed;
  const preflight: { ok: boolean; label: string; detail?: string }[] = [
    { ok: !!selectedWorkflow && selectedWorkflow.ready !== false, label: "工作流可用", detail: selectedWorkflow ? `${selectedWorkflow.name}${selectedWorkflow.ready === false ? " · " + (selectedWorkflow.validation?.errors.map(issue => issue.message).join("；") || "校验未通过") : ""}` : workflowLoading ? "正在读取" : "未选择" },
    { ok: !!draft.prompt.trim(), label: "已写描述" },
    { ok: !unresolvedConnections, label: "连线用途已确认" },
    { ok: !missingVersions.length, label: "参考原件可读取", detail: missingVersions.length ? `${missingVersions.length} 个版本缺失` : undefined },
    { ok: !limits || (references.length >= limits.min_images && references.length <= limits.max_images), label: `参考数量 ${references.length}`, detail: limits ? `此工作流接收 ${limits.min_images}–${limits.max_images} 张` : undefined },
    { ok: !limits || (!(limits.requires_mask && !draft.mask_version_id) && !(draft.mask_version_id && !limits.supports_mask)), label: "蒙版要求", detail: limits?.requires_mask ? "需要蒙版" : draft.mask_version_id ? "已附蒙版" : "无需蒙版" },
    { ok: isOpenAI || seedValue === undefined || (Number.isSafeInteger(seedValue) && Number(seedValue) >= -1), label: "种子有效" },
    { ok: !active && job?.status !== "unknown", label: "此卡片没有进行中的一轮", detail: active || job?.status === "unknown" ? "本机服务对同一节点一次只运行一轮：等它结束、核对或取消后再提交" : undefined },
  ];
  const unsentParameters = selectedWorkflow ? Object.keys(draft.parameters).filter(key => ["seed", "width", "height", "steps", "cfg", "denoise"].includes(key) && !selectedWorkflow.bindings[key as "seed"]?.length) : [];
  const advancedCount = selectedWorkflow && !isOpenAI ? (["steps", "cfg", "denoise"] as const).filter(key => draft.parameters[key] !== undefined && Number(draft.parameters[key]) !== Number(selectedWorkflow.defaults[key] ?? NaN)).length
    + (draft.parameters.negative_prompt !== undefined && draft.parameters.negative_prompt !== (selectedWorkflow.defaults.negative_prompt ?? "") ? 1 : 0)
    + (seedValue !== undefined && Number(seedValue) !== -1 ? 1 : 0) : 0;
  const effectiveRequest = showEffective ? (pendingSubmission || (selectedWorkflow ? buildRequest() : null)) : null;
  const parameterNames: Record<string, string> = { seed: "种子", width: "宽", height: "高", steps: "步数", cfg: "提示强度", denoise: "重绘幅度" };
  const composerRect = composerRoot.current?.getBoundingClientRect();
  const pickerPosition = {
    left: Math.max(12, Math.min((composerRect?.left || 12) + 20, window.innerWidth - Math.min(560, window.innerWidth - 24) - 12)),
    top: Math.max(12, Math.min(composerRect && composerRect.top >= 340 ? composerRect.top - 325 : (composerRect?.top || 60) + 40, window.innerHeight - 330)),
    width: Math.min(560, window.innerWidth - 24),
  };

  return (
    <div
      ref={composerRoot}
      className={"generation-composer nodrag nopan nowheel"+(collapsed?" is-collapsed":"")}
      onKeyDown={event => { if (event.key === "Escape") { setPickerOpen(false); setSizeOpen(false); setPresetOpen(null); setReferencePreview(null); } }}
      onPointerDown={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      <div className="composer-compact-toolbar"><span>图片创作</span><button className="composer-rounds-link" onClick={()=>window.dispatchEvent(new CustomEvent("manju:open-rounds",{detail:{nodeId}}))} title="查看这张卡片每一轮提交与结果">结果轮次</button><button onClick={()=>setExpanded(value=>!value)} aria-expanded={expanded}>创作预设</button><button aria-label={collapsed?"展开创作面板":"收起创作面板"} onClick={()=>setCollapsed(value=>!value)}>{collapsed?"展开":"收起"}</button></div>
      {draft.refill_of && (
        <div className="composer-refill" role="status">
          <span className="composer-refill-tag">回填</span>
          <span>来自 {new Date(draft.refill_of.created_at).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"})} 的一轮。修改后点生成会成为新的一轮，原记录不变。</span>
          {draft.refill_of.seed !== undefined && selectedWorkflow?.bindings.seed.length ? (draft.parameters.seed === -1
            ? <button disabled={disabledEditing} onClick={()=>{onBeginEdit();updateDraft({parameters:{...draftRef.current.parameters,seed:draft.refill_of!.seed!}});}}>沿用原种子 {draft.refill_of.seed}</button>
            : <button disabled={disabledEditing} onClick={()=>{onBeginEdit();updateDraft({parameters:{...draftRef.current.parameters,seed:-1}});}}>改用随机种子</button>) : null}
          <button aria-label="清除回填标记" title="清除回填标记（草稿内容保留）" disabled={disabledEditing} onClick={()=>updateDraft({refill_of:undefined})}><X size={12} /></button>
        </div>
      )}
      {isOpenAI && <OpenAIImageControls options={openaiOptions} catalog={openai.catalog} estimate={openai.estimate} issue={openai.issue} loading={openai.catalogLoading} disabled={disabledEditing} referenceCount={references.length} onRefresh={openai.refresh} onChange={options=>{onBeginEdit();updateDraft({model:options.model,quality:options.quality,parameters:{...draftRef.current.parameters,width:options.width,height:options.height}});}}/>}
      {!!unresolvedConnections && <div className="reference-notice" role="alert">旧连线用途待确认 <button onClick={()=>onConfirmConnections?.("relation")}>作为故事关系</button><button onClick={()=>onConfirmConnections?.("reference")}>作为图片参考</button></div>}
      {references.length>0 && draft.mode==="text_to_image" && <div className="reference-notice">已添加固定参考图。<button onClick={()=>changeMode("reference")}>切换到参考生图</button></div>}
      <div style={{display:expanded?undefined:"none"}} className="studio-preset-rail" aria-label="画面描述预设">
        {([{ id: "camera", label: "镜头语言", Icon: Camera }, { id: "style", label: "画面风格", Icon: Palette }, { id: "light", label: "光线氛围", Icon: Sun }] as const).map(({ id, label, Icon }) => <button key={id} disabled={disabledEditing} aria-expanded={presetOpen === id} onClick={() => { setPresetOpen(value => value === id ? null : id); setPickerOpen(false); setSizeOpen(false); }}><span className={`studio-preset-icon ${id}`}><Icon size={18} strokeWidth={1.6} /></span><span>{label}</span><ChevronDown size={13} /></button>)}
      </div>
      {presetOpen && <div className="studio-presets"><span>添加到画面描述</span><div>{creativePresets[presetOpen].map(preset => <button key={preset.label} onClick={() => addPreset(preset.text)} title={preset.text}>{preset.label}</button>)}</div></div>}
      <div className="generation-reference-list" aria-label="生成引用图片">
        {references.map((reference,index)=><ReferenceTile key={reference.version_id} reference={reference} index={index} badge={draft.mode==="edit"&&index===0?"底图":undefined}
          disabled={disabledEditing} onHover={hoverReference} onOpen={openReference}
          onMove={direction=>reorderReference(index,direction)} canMoveBack={index!==0&&!(draft.mode==="edit"&&!!versionId&&index===1)} canMoveForward={index!==references.length-1&&!(draft.mode==="edit"&&!!versionId&&index===0)}
          onRemove={draft.mode==="edit"&&!!versionId&&reference.source==="base"?undefined:()=>removeReference(reference)}>
          {reference.node_id && !sourceVersions[reference.node_id] && <span className="reference-status">来源卡已删除／无图</span>}
          {reference.node_id && sourceVersions[reference.node_id] && ((reference.source==="connection" ? sourceVersions[reference.node_id]!==reference.version_id : !sourceImages[reference.node_id]?.includes(reference.version_id)) || (sourceDescriptions[reference.node_id]!==undefined && sourceDescriptions[reference.node_id]!==reference.description)) && <button className="reference-status" disabled={disabledEditing} onClick={()=>setUpdateCandidate(reference)}>来源有新图 · 更新</button>}
          {missingVersions.includes(reference.version_id) && <span className="reference-status error">原件缺失</span>}
        </ReferenceTile>)}
        <button className="studio-add-reference" title="添加参考图片" aria-label="添加参考图片" disabled={disabledEditing} aria-expanded={pickerOpen} onClick={openPicker}><Plus size={24} strokeWidth={1.3} />{!references.length && <span>参考图片</span>}</button>
        {!references.length && <div className="studio-reference-empty"><strong>让画面有据可依</strong><span>添加参考图，或输入 @ 引用画布图片</span></div>}
        <span className="studio-mode-caption">{workflowModeNames[draft.mode]}</span>
      </div>
      {references.some(ref=>ref.description) && <label className="reference-description-option"><input type="checkbox" checked={references.filter(ref=>ref.description).every(ref=>ref.use_description!==false)} onChange={event=>{onBeginEdit();updateDraft({references:(draft.references||[]).map(ref=>({...ref,use_description:event.target.checked}))});}} />使用主体设定</label>}
      {updateCandidate && createPortal(<div className="modal-shade"><div className="modal modal-wide" role="dialog" aria-label="更新固定参考"><header className="modal-heading"><h2>更新固定参考</h2></header><div className="reference-compare"><figure><img src={mediaUrl(updateCandidate.version_id)} /><figcaption>当前固定图片</figcaption></figure><figure><img src={mediaUrl(sourceVersions[updateCandidate.node_id!] || updateCandidate.version_id)} /><figcaption>来源当前主图（同时更新主体设定）</figcaption></figure></div><footer className="modal-footer"><button onClick={()=>setUpdateCandidate(null)}>取消</button><button onClick={()=>{onUpdateReference?.(updateCandidate);setUpdateCandidate(null);}}>更新引用</button></footer></div></div>,document.body)}
      <div className="generation-prompt-wrap">
        <PromptEditor ref={textarea} value={draft.prompt} references={references} placeholder={draft.mode === "edit" ? "描述你想修改的地方，试试 @ 引用另一张图片…" : "描述你想创作的画面，试试 @ 引用角色或场景…"} disabled={disabledEditing} onFocus={onBeginEdit}
          onReferenceHover={hoverReference}
          onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
          onChange={changePrompt}
          onKeyDown={event => {
            if (composing.current || event.nativeEvent.isComposing) return;
            if (pickerOpen && event.key === "ArrowDown") { event.preventDefault(); setPickerIndex(index => Math.min(index + 1, pickerAssets.length - 1)); }
            else if (pickerOpen && event.key === "ArrowUp") { event.preventDefault(); setPickerIndex(index => Math.max(0, index - 1)); }
            else if (pickerOpen && !pickerLoading && event.key === "Enter" && pickerAssets[pickerIndex] && !event.ctrlKey && !event.metaKey) { event.preventDefault(); selectReference(pickerAssets[pickerIndex]); }
            else if (pickerOpen && event.key === "Escape") { event.preventDefault(); setPickerOpen(false); mentionRange.current = null; }
            else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void submit(); }
          }} />
      </div>
      {draft.mode === "edit" && selectedWorkflow?.capabilities.supports_mask && <div className="studio-edit-tools"><button className={`generation-mask-toggle ${draft.mask_version_id ? "has-mask" : ""}`} disabled={disabledEditing || !references.length} aria-expanded={showMaskTools} onClick={() => setShowMaskTools(value => !value)}><Brush size={14} />{draft.mask_version_id ? "已设置局部编辑区域" : "局部编辑"}<ChevronDown size={12} /></button></div>}
      {pickerOpen && createPortal(
        <div className="generation-reference-picker studio-reference-picker-overlay" role="dialog" aria-label="选择引用图片" style={pickerPosition} onPointerDown={event => event.stopPropagation()}>
          <div className="generation-picker-heading">
            <strong>引用图片</strong>
            <div>
              <button
                className={pickerScope === "canvas" ? "active" : ""}
                onClick={() => setPickerScope("canvas")}
              >
                画布图片
              </button>
              <button className={pickerScope === "subjects" ? "active" : ""} onClick={() => setPickerScope("subjects")}>主体库</button>
              <button
                className={pickerScope === "all" ? "active" : ""}
                onClick={() => setPickerScope("all")}
              >
                全部资产
              </button>
            </div>
            <button
              title="关闭图片选择"
              onClick={() => {
                setPickerOpen(false);
                mentionRange.current = null;
              }}
            >
              <X size={14} />
            </button>
          </div>
          <label>
            <Search size={13} />
            <input
              aria-label="搜索引用图片"
              placeholder="按名称查找图片"
              value={pickerQuery}
              onChange={(event) => setPickerQuery(event.target.value)}
            />
          </label>
          <div className="generation-picker-results">
            {pickerLoading ? (
              <span className="generation-picker-empty">
                <LoaderCircle className="spin" size={16} />
                正在查找图片
              </span>
            ) : pickerAssets.length ? (
              pickerAssets.map((reference, index) => (
                <button
                  className={index === pickerIndex ? "focused" : ""}
                  disabled={disabledEditing || pickerLoading}
                  key={`${reference.version_id}:${reference.node_id || index}`}
                  onClick={() => selectReference(reference)}
                >
                  <img src={mediaUrl(reference.version_id)} alt="" />
                  <span>{reference.title}</span>
                  {references.some(
                    (item) => item.version_id === reference.version_id,
                  ) && <Check size={12} />}
                </button>
              ))
            ) : (
              <span className="generation-picker-empty">
                没有匹配图片，可切换到全部资产或先导入图片。
              </span>
            )}
          </div>
        </div>, document.body
      )}
      {showMaskTools && draft.mode === "edit" &&
        selectedWorkflow?.capabilities.supports_mask && (
          <div className="generation-mask-row">
            {draft.mask_version_id ? (
              <div className="generation-mask-chip">
                <img src={mediaUrl(draft.mask_version_id)} alt="编辑蒙版" />
                <span>已设置局部编辑蒙版</span>
                <button
                  title="移除蒙版，进行整图编辑"
                  disabled={disabledEditing}
                  onClick={() => {
                    onBeginEdit();
                    updateDraft({ mask_version_id: undefined });
                  }}
                >
                  <X size={12} />
                </button>
              </div>
            ) : (
              <span>整图指令编辑</span>
            )}
            <button
              disabled={disabledEditing || !references.length}
              onClick={() => setMaskEditor(true)}
            >
              <Brush size={13} />
              绘制蒙版
            </button>
            <button
              disabled={disabledEditing || !references.length || maskUploading}
              onClick={() => maskInput.current?.click()}
            >
              {maskUploading ? (
                <LoaderCircle className="spin" size={13} />
              ) : (
                <Upload size={13} />
              )}
              上传
            </button>
          </div>
        )}
      {draft.mask_version_id &&
        !selectedWorkflow?.capabilities.supports_mask && (
          <button
            className="generation-remove-mask"
            onClick={() => {
              onBeginEdit();
              updateDraft({ mask_version_id: undefined });
            }}
          >
            <X size={12} />
            移除不适用的蒙版
          </button>
        )}
      {sizeOpen && !isOpenAI && <section className="studio-size-panel" aria-label="画幅与尺寸">
        <header><strong>画幅与尺寸</strong><span>{currentWidth} × {currentHeight} px</span><button title="关闭尺寸设置" onClick={() => setSizeOpen(false)}><X size={14} /></button></header>
        <div className="studio-ratios">{ratios.map(ratio => <button key={ratio.label} aria-label={`画幅 ${ratio.label}`} aria-pressed={currentRatio?.label === ratio.label} disabled={disabledEditing || !canSetSize} onClick={() => setSize(ratio)}><i style={{ width: ratio.width >= ratio.height ? 24 : 24 * ratio.width / ratio.height, height: ratio.height >= ratio.width ? 24 : 24 * ratio.height / ratio.width }} /><span>{ratio.label}</span></button>)}</div>
        <div className="studio-resolutions"><span>长边</span>{[512, 1024, 2048].map(size => <button key={size} aria-label={`长边 ${size} 像素`} aria-pressed={currentLongEdge === size} disabled={disabledEditing || !canSetSize} onClick={() => setSize(undefined, size)}>{size === 512 ? "512 px" : size === 1024 ? "1K" : "2K"}</button>)}<button className="studio-custom-size" onClick={() => { setShowParameters(true); setSizeOpen(false); }}>自定义尺寸</button></div>
      </section>}
      {showParameters && !isOpenAI && (
        <section className="generation-settings">
          <header><strong>生成设置</strong><a href="#/workflows">管理工作流<ArrowUpRight size={12} /></a><button title="刷新工作流" onClick={() => void refreshWorkflows()}><RefreshCw size={13} /></button><button title="关闭生成设置" onClick={() => setShowParameters(false)}><X size={14} /></button></header>
        <div className="generation-parameters">
          {selectedWorkflow && Object.keys(draft.parameters).some(key=>{const binding=selectedWorkflow.bindings[key as keyof Workflow["bindings"]];return !Array.isArray(binding) || !binding.length;}) && <p className="reference-notice">此工作流未绑定的参数会保留在草稿中，本次生成不使用。</p>}
          {parameterFields.map((field) => (
            <label key={field.key}>
              {field.label}
              <input
                aria-label={`生成${field.label}`}
                type="number"
                min={field.min}
                max={field.max}
                step={field.step}
                value={
                  draft.parameters[field.key] ??
                  selectedWorkflow?.defaults[field.key] ??
                  field.fallback
                }
                disabled={disabledEditing}
                onFocus={onBeginEdit}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (Number.isFinite(value))
                    updateDraft({
                      parameters: {
                        ...draftRef.current.parameters,
                        [field.key]: value,
                      },
                    });
                }}
              />
              {field.key === "seed" && <small>-1 表示随机</small>}
            </label>
          ))}
          {selectedWorkflow &&
            selectedWorkflow.bindings.negative_prompt.length > 0 && (
              <label className="generation-negative">
                避免出现
                <input
                  value={
                    draft.parameters.negative_prompt ??
                    selectedWorkflow.defaults.negative_prompt ??
                    ""
                  }
                  disabled={disabledEditing}
                  onFocus={onBeginEdit}
                  onChange={(event) =>
                    updateDraft({
                      parameters: {
                        ...draftRef.current.parameters,
                        negative_prompt: event.target.value,
                      },
                    })
                  }
                />
              </label>
            )}
        </div>
        </section>
      )}
      {(workflowError || capabilityError) && (
        <details className="generation-notice">
          <summary><AlertCircle size={13} /><span>{workflowError || capabilityError}</span><ChevronDown size={12} /></summary>
          <p>{workflowError || capabilityError}</p>
          <a href="#/workflows">检查工作流<ArrowUpRight size={11} /></a>
        </details>
      )}
      {pendingSubmission && (
        <p className="generation-validation">上次提交待确认，重试将继续同一个请求。</p>
      )}
      {error && (
        <details className="generation-error generation-submit-error" role="alert">
          <summary><AlertCircle size={13} /><span>{error}</span><ChevronDown size={12} /></summary>
          <div><p>{error}</p><button title="关闭生图错误" onClick={() => setError("")}><X size={12} />关闭提示</button></div>
        </details>
      )}
      <GenerationProgress job={job || undefined} compact/>
      {job && (
        <div className={`generation-job ${job.status}`}>
          {job.request?.provider==="openai" && (job.status==="failed" || job.status==="cancelled") && <p className="openai-cloud-note">重试沿用原任务的模型与参数。原图片输出预估：${Number((job.request.cost_estimate as {output_usd?:number}|undefined)?.output_usd || 0).toFixed(5)} + 输入费用；已有本地结果时仅重试保存。</p>}
          <div className="generation-job-summary">
            {active ? <LoaderCircle className="spin" size={13} /> : job.status === "succeeded" ? <Check size={13} /> : <AlertCircle size={13} />}
            <span>{job.status === "succeeded" && job.outputs.some(output => output.node_id === nodeId) ? "已更新当前图片" : generationStateLabels[job.status]}</span>
            <div className="generation-job-actions">
              {active && <button disabled={jobAction || job.can_cancel === false} onClick={() => void jobOperation("cancel")}><CircleStop size={12} />取消</button>}
              {(job.status === "failed" || job.status === "cancelled") && <button disabled={jobAction || submitting || job.can_retry === false} onClick={() => void jobOperation("retry")}><RefreshCw size={12} />重试</button>}
              {job.status === "unknown" && <><button disabled={jobAction} onClick={() => void refreshJob()}>核对状态</button>{<button disabled={jobAction} onClick={()=>void jobOperation("cancel")}>结束跟踪</button>}</>}
              {job.status === "succeeded" && resultNodeId && <button onClick={() => onReveal(resultNodeId)}><Maximize2 size={12} />查看结果</button>}
              <button title="生成任务详情" aria-expanded={showJobDetails} onClick={() => setShowJobDetails(value => !value)}><ChevronDown size={13} /></button>
            </div>
          </div>
          {active && <div className="generation-stage-indicator" aria-label={generationStateLabels[job.status]}><i /></div>}
          {showJobDetails && <div className="generation-job-details">
            {job.message && job.message !== generationStateLabels[job.status] && <p>{job.message}</p>}
            {jobError && <p>{jobError}</p>}
            {job.request?.provider==="openai" && <p>模型：{String(job.request.model)} · 画质：{String(job.request.quality)}{(job.request.actual_cost as {total_usd?:number}|undefined)?.total_usd!==undefined?` · 按返回用量计费 $${(job.request.actual_cost as {total_usd:number}).total_usd.toFixed(5)}`:""}</p>}
            {job.error && typeof job.error !== "string" && <details className="generation-error-details"><summary>查看错误详情</summary><pre>{JSON.stringify(job.error, null, 2)}</pre></details>}
            {job.status === "unknown" && <p>{job.request?.provider==="openai"?"原 OpenAI 请求可能已计费。请核对平台用量；结束跟踪后可重新生成。":"正在核对 ComfyUI 原提交。可以继续等待或核对后结束本地跟踪，原任务不会自动重复提交。"}</p>}
          </div>}
          {confirmCancellation && <div className="generation-cancel-confirm"><p>{job.request?.provider==="openai"?"结束跟踪不会撤回云端请求，原请求可能已计费。":job.status==="unknown"?"结束本地跟踪不会撤回 ComfyUI 原任务，原任务可能仍在运行。":"取消会中断当前生成。"}</p><button disabled={jobAction} onClick={() => void jobOperation("cancel", true)}>{job.status==="unknown"?"已核对，结束跟踪":"确认取消本次生成"}</button><button disabled={jobAction} onClick={() => setConfirmCancellation(false)}>继续等待</button></div>}
        </div>
      )}
      {showEffective && (
        <section className="composer-effective" aria-label="提交前检查与实际提交">
          <h4>提交前检查</h4>
          <ul className="composer-preflight">
            {preflight.map(item => <li key={item.label} className={item.ok ? "ok" : "bad"}>{item.ok ? <Check size={12} /> : <AlertCircle size={12} />}<span>{item.label}{item.detail && <small>{item.detail}</small>}</span></li>)}
          </ul>
          {capabilityError && <p className="composer-effective-block">暂不能提交：{capabilityError}</p>}
          {effectiveRequest ? <>
            <h4>实际提交{pendingSubmission ? "（重试沿用上次的同一个请求）" : ""}</h4>
            <dl className="composer-effective-list">
              <dt>去向</dt><dd>{effectiveRequest.provider === "openai" ? "云端 OpenAI · 会计费，描述与参考图会离开本机" : "本机 ComfyUI"}</dd>
              <dt>工作流</dt><dd>{selectedWorkflow?.name || effectiveRequest.workflow_id} <code>{effectiveRequest.workflow_id}</code></dd>
              <dt>方式</dt><dd>{workflowModeNames[draft.mode]}</dd>
              <dt>描述</dt><dd className="composer-effective-prompt">{effectiveRequest.prompt || "（空）"}</dd>
              {effectiveRequest.negative_prompt ? <><dt>负面</dt><dd>{effectiveRequest.negative_prompt}</dd></> : null}
              {Object.entries(effectiveRequest.parameters).map(([key, value]) => <Fragment key={key}><dt>{parameterNames[key] || key}</dt><dd>{key === "seed" && Number(value) === -1 ? "随机（提交时由本机服务生成，并写入这一轮的记录）" : String(value)}</dd></Fragment>)}
              {unsentParameters.length ? <><dt>不送出</dt><dd>{unsentParameters.map(key => parameterNames[key] || key).join("、")}（当前工作流没有对应输入）</dd></> : null}
              <dt>参考</dt><dd>{effectiveRequest.references.length ? <ol>{effectiveRequest.references.map((ref, index) => <li key={ref.version_id}>@{index + 1} {ref.title || "参考"} · 版本 <code>{ref.version_id.slice(0, 8)}</code>{draft.mode === "edit" && index === 0 ? " · 编辑底图" : ""}</li>)}</ol> : "无"}</dd>
              {effectiveRequest.mask_version_id ? <><dt>蒙版</dt><dd><code>{effectiveRequest.mask_version_id.slice(0, 8)}</code></dd></> : null}
            </dl>
            <details className="composer-effective-raw"><summary>查看完整请求</summary><pre>{JSON.stringify({ ...effectiveRequest, request_id: pendingSubmission ? effectiveRequest.request_id : "（提交时生成）" }, null, 2)}</pre></details>
          </> : <p className="composer-effective-block">选择可用工作流后显示将要提交的内容。</p>}
        </section>
      )}
      <footer className="generation-footer">
        <label className="generation-mode-select" title="创作方式">
          <StudioSelect
            aria-label="创作方式"
            value={draft.mode}
            disabled={disabledEditing}
            onChange={event => changeMode(event.target.value as WorkflowMode)}
          >
            {(["text_to_image", "reference", "edit"] as WorkflowMode[]).map(mode => <option key={mode} value={mode}>{workflowModeNames[mode]}</option>)}
          </StudioSelect>
          <ChevronDown size={11} />
        </label>
        <label className="generation-workflow" title={selectedWorkflow?.name || "选择工作流"}>
          <StudioSelect
            aria-label="生图工作流"
            value={selectedWorkflow?.id || ""}
            disabled={disabledEditing || workflowLoading}
            onChange={event => {
              onBeginEdit();
              const previous=selectedWorkflow?.id || "default";
              const nextWorkflow=availableWorkflows.find(item=>item.id===event.target.value);
              updateDraft({workflow_id:event.target.value,workflow_import_warning:undefined,workflow_drafts:{...draft.workflow_drafts,[previous]:draft.parameters},parameters:draft.workflow_drafts?.[event.target.value] || (nextWorkflow?.provider==="openai"?{width:1024,height:1024}:draft.parameters)});
            }}
          >
            <option value="" disabled>{workflowLoading ? "读取中…" : availableWorkflows.length ? "选择工作流" : "暂无工作流"}</option>
            {availableWorkflows.map(workflow => <option key={workflow.id} value={workflow.id}>{workflow.provider==="openai"?workflow.name:workflow.builtin ? workflow.name.split(" · ")[0] : workflow.name}{workflow.ready === false ? workflow.provider==="openai"?" · 待配置":" · 待修复" : ""}</option>)}
          </StudioSelect>
          <ChevronDown size={11} />
        </label>
        {!isOpenAI && <button className="studio-size-toggle" aria-label="画幅与尺寸" aria-expanded={sizeOpen} title={canSetSize ? `${currentWidth} × ${currentHeight} 像素` : "输出尺寸由当前工作流决定"} disabled={disabledEditing || !canSetSize} onClick={() => { setSizeOpen(value => !value); setShowParameters(false); setPresetOpen(null); setPickerOpen(false); }}><span>{canSetSize ? currentRatio?.label || "自定义" : "原始尺寸"}</span><span className="studio-dot">·</span><span>{canSetSize ? currentLongEdge === 1024 ? "1K" : currentLongEdge === 2048 ? "2K" : `${currentLongEdge}px` : "工作流"}</span><ChevronDown size={13} /></button>}
        <button className="studio-mention-toggle" aria-label="引用图片" title="引用图片 · @" disabled={disabledEditing} aria-expanded={pickerOpen} onClick={openPicker}><AtSign size={19} /></button>
        {!isOpenAI && <button className="generation-parameters-toggle" title={advancedCount ? `高级参数 · 已调整 ${advancedCount} 项` : "高级参数"} aria-label={advancedCount ? `高级参数，已调整 ${advancedCount} 项` : "高级参数"} aria-expanded={showParameters} onClick={() => setShowParameters(value => !value)}><Settings2 size={15} />{advancedCount > 0 && <b className="composer-adv-count">{advancedCount}</b>}</button>}
        <button className={"composer-effective-toggle" + (capabilityError ? " has-issue" : "")} aria-expanded={showEffective} title="提交前检查与实际提交内容" onClick={() => { setShowEffective(value => !value); setSizeOpen(false); setPickerOpen(false); setPresetOpen(null); }}>{capabilityError ? <AlertCircle size={13} /> : <Check size={13} />}<span>实际提交</span></button>
        <span className="studio-output-count" title={isOpenAI ? "每次生成 1 张，费用预估见上方" : selectedWorkflow?.builtin ? "当前工作流每次生成 1 张图片" : "出图数量由工作流决定"}><Sparkles size={13} />{isOpenAI&&openai.estimate?`≈ $${openai.estimate.output_usd.toFixed(4)} + 输入`:selectedWorkflow?.builtin ? "1 张" : "按工作流输出"}</span>
        <button
          className="generation-submit"
          aria-label={pendingSubmission ? "重试提交" : draft.mode === "edit" ? "生成编辑结果" : "生成图片"}
          title={canSubmit ? "生成 · Ctrl+Enter，结果保留在当前卡片" : capabilityError || (!draft.prompt.trim() ? "先描述你想创作的画面" : "生成正在进行")}
          disabled={!canSubmit || job?.status === "unknown"}
          onClick={() => void submit()}
        >
          {submitting || active ? <LoaderCircle className="spin" size={22} /> : pendingSubmission ? <RefreshCw size={21} /> : <ArrowUp size={24} strokeWidth={2.2} />}
        </button>
      </footer>
      {renderReferencePreview(references)}
      <input
        hidden
        ref={maskInput}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void uploadMask(file);
          event.target.value = "";
        }}
      />
      {maskEditor &&
        references[0] &&
        createPortal(
          <MaskEditor
            projectId={projectId}
            versionId={references[0].version_id}
            onClose={() => setMaskEditor(false)}
            onSave={(maskVersionId) => {
              onBeginEdit();
              updateDraft({ mask_version_id: maskVersionId });
              setMaskEditor(false);
              onAssetsChange();
            }}
          />,
          document.body,
        )}
    </div>
  );
}
