import { useEffect, useRef, useState } from "react";
import { ArrowUp, Film, LoaderCircle, Square } from "lucide-react";
import { api, ApiError, mediaUrl } from "./api";
import { GenerationProgress, useGenerationJob } from "./GenerationProgress";
import { activeGenerationStates, generationStateLabels, VIDEO_INTERPOLATE_WORKFLOW, VIDEO_UPSCALE_WORKFLOW, VIDEO_WATERMARK_WORKFLOW } from "./generationTypes";
import type { GenerationDraft, GenerationJob, GenerationRequest, ImageReference, VideoEnhanceMethod, VideoEnhanceOptions, VideoEnhanceWorkflow, WatermarkOptions } from "./generationTypes";
import StudioSelect from "./StudioSelect";
import "./video.css";

export const videoEnhanceLabels = {
  [VIDEO_INTERPOLATE_WORKFLOW]: "视频补帧",
  [VIDEO_UPSCALE_WORKFLOW]: "视频放大",
  [VIDEO_WATERMARK_WORKFLOW]: "视频水印",
};

const methodOptions: Partial<Record<VideoEnhanceWorkflow, { id: VideoEnhanceMethod; name: string; description: string }[]>> = {
  [VIDEO_INTERPOLATE_WORKFLOW]: [
    { id: "rife", name: "RIFE · AI 补帧", description: "生成中间画面。填写切点可避免跨镜头补帧。" },
    { id: "hold", name: "重复原帧", description: "按目标帧率重复原帧，保留原画的停顿节奏。" },
  ],
  [VIDEO_UPSCALE_WORKFLOW]: [
    { id: "anime6b", name: "Anime6B · 动画", description: "适合动画线条和平涂色块。" },
    { id: "remacri", name: "Remacri · 纹理", description: "侧重纹理和边缘细节。" },
  ],
};
const fpsPresets = [24, 25, 30, 48, 50, 60, 120];
const resolutionPresets = [
  { width: 1280, height: 720 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
  { width: 3840, height: 2160 },
];
type EnhanceProfile = { ready: boolean; methods?: { id: VideoEnhanceMethod; name: string; ready: boolean }[] };
const defaultWatermark: WatermarkOptions = { mode: "text", text: "", position: "bottom-right", size: 4, opacity: 65, color: "#ffffff" };

export function defaultVideoEnhanceDraft(workflowId: VideoEnhanceWorkflow): GenerationDraft {
  return {
    kind: "video", workflow_id: workflowId, mode: "text_to_image", prompt: "", references: [], parameters: {},
    ...(workflowId === VIDEO_WATERMARK_WORKFLOW ? { watermark_options: defaultWatermark } : {
      enhance_options: workflowId === VIDEO_INTERPOLATE_WORKFLOW ? { method: "rife", fps: 60, cuts: [] } : { method: "anime6b", width: 3840, height: 2160 },
    }),
  };
}

function parseCuts(text: string): number[] | undefined {
  const tokens = text.split(/[\s,，]+/).filter(Boolean);
  const cuts = tokens.map(Number);
  if (tokens.length > 4096 || tokens.some((token, index) => !/^\d+$/.test(token) || cuts[index] >= 2 ** 31 || cuts[index] <= (cuts[index - 1] ?? 0))) return;
  return cuts;
}

function inRange(value: number | undefined, min: number, max: number, step = 1) {
  return value !== undefined && Number.isInteger(value) && value >= min && value <= max && value % step === 0;
}

type Props = {
  projectId: string;
  nodeId: string;
  workflowId: VideoEnhanceWorkflow;
  draft: GenerationDraft;
  locked?: boolean;
  input?: ImageReference;
  getInput: () => ImageReference | undefined;
  logo?: ImageReference;
  getLogo: () => ImageReference | undefined;
  mediaRevisions: Record<string, number>;
  onPreview: (versionId: string) => void;
  onChange: (patch: Partial<GenerationDraft>) => void;
  onBeginEdit: () => void;
  onBeforeSubmit: () => Promise<void>;
};

export default function VideoEnhanceComposer(props: Props) {
  const { draft, input, workflowId } = props;
  const interpolate = workflowId === VIDEO_INTERPOLATE_WORKFLOW;
  const watermark = workflowId === VIDEO_WATERMARK_WORKFLOW;
  const label = videoEnhanceLabels[workflowId];
  const methods = methodOptions[workflowId] ?? [];
  const options = { ...defaultVideoEnhanceDraft(workflowId).enhance_options, ...draft.enhance_options };
  const mark = { ...defaultWatermark, ...draft.watermark_options };
  const method = methods.find(item => item.id === options.method);
  const [profile, setProfile] = useState<EnhanceProfile>();
  const [profileError, setProfileError] = useState(false);
  const [customPreset, setCustomPreset] = useState(false);
  const [cutText, setCutText] = useState(() => options.cuts?.join(", ") ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [latestJob, setLatestJob] = useState<GenerationJob>();
  const inFlight = useRef(false);
  const primaryNumber = useRef<HTMLInputElement>(null);
  const job = useGenerationJob(draft.last_job_id) ?? (latestJob?.id === draft.last_job_id ? latestJob : undefined);
  const active = !!job && activeGenerationStates.has(job.status);
  const pending = draft.pending_submission;
  const blocked = props.locked || busy || active || !!pending;
  const cuts = parseCuts(cutText);
  const rife = method?.id === "rife";
  const resolutionPreset = resolutionPresets.find(size => size.width === options.width && size.height === options.height);
  const preset = !customPreset && (interpolate
    ? options.fps !== undefined && fpsPresets.includes(options.fps) && String(options.fps)
    : resolutionPreset && String(resolutionPreset.height)) || "custom";

  useEffect(() => {
    const controller = new AbortController();
    api<EnhanceProfile>(`/api/workflows/${workflowId}`, { signal: controller.signal })
      .then(setProfile).catch(() => { if (!controller.signal.aborted) setProfileError(true); });
    return () => controller.abort();
  }, [workflowId]);

  function methodReady(id: VideoEnhanceMethod) {
    const advertised = profile?.methods?.find(item => item.id === id);
    return advertised?.ready ?? (id === methods[0]?.id && profile?.ready !== false);
  }

  const markReady = mark.mode === "text" ? !!mark.text.trim() : !!props.logo;
  const invalid = watermark ? profile?.ready === false ? "烧录水印需要本机 FFmpeg 和 FFprobe。" : !markReady
    ? mark.mode === "text" ? "请输入水印文字。" : "请把 Logo 图片卡片连接到这里。" : ""
    : !method ? "请选择处理模式。" : !methodReady(method.id) ? "当前处理模式在本机不可用。" : interpolate
    ? !inRange(options.fps, 1, 120) ? "目标帧率须为 1–120 的整数。"
      : rife && !cuts ? "切点须为严格递增的正整数，最多 4096 个。" : ""
    : !inRange(options.width, 64, 4096, 2) || !inRange(options.height, 64, 4096, 2)
      ? "目标宽高均须为 64–4096 的偶数。" : "";

  function setNumber(key: "fps" | "width" | "height", value: string) {
    setCustomPreset(true);
    props.onChange({ enhance_options: { ...options, [key]: value === "" ? undefined : Number(value) } });
  }

  function setPreset(value: string) {
    props.onBeginEdit();
    setCustomPreset(value === "custom");
    if (value === "custom") {
      primaryNumber.current?.focus();
    } else if (interpolate) {
      props.onChange({ enhance_options: { ...options, fps: Number(value) } });
    } else {
      const size = resolutionPresets.find(item => item.height === Number(value));
      if (size) props.onChange({ enhance_options: { ...options, ...size } });
    }
  }

  function updateCuts(value: string) {
    setCutText(value);
    const parsed = parseCuts(value);
    if (parsed) props.onChange({ enhance_options: { ...options, cuts: parsed } });
  }

  async function submit() {
    if (props.locked || active || inFlight.current || (!pending && invalid)) return;
    let request: GenerationRequest | undefined = pending;
    if (!request) {
      const reference = props.getInput();
      if (!reference) {
        setError("请连接一张已有视频素材的上游卡片。");
        return;
      }
      const logo = watermark && mark.mode === "image" ? props.getLogo() : undefined;
      if (watermark && mark.mode === "image" && !logo) {
        setError("请把 Logo 图片卡片连接到这里。");
        return;
      }
      const enhanceOptions: VideoEnhanceOptions = interpolate
        ? { method: method?.id, fps: options.fps, cuts: rife ? cuts : [] }
        : { method: method?.id, width: options.width, height: options.height };
      const references = logo ? [reference, logo] : [reference];
      request = {
        kind: "video", project_id: props.projectId, source_node_id: props.nodeId,
        workflow_id: workflowId, mode: "text_to_image", prompt: "", references,
        ...(watermark ? { watermark_options: mark } : { enhance_options: enhanceOptions }),
        parameters: {}, placement: { x: 0, y: 0 }, result_policy: "replace",
        request_id: crypto.randomUUID(),
      };
      props.onChange({
        prompt: "", references, ...(watermark ? { watermark_options: mark } : { enhance_options: { ...options, ...(rife ? { cuts } : {}) } }), parameters: {},
        pending_request_id: request.request_id, pending_submission: request,
      });
    }
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await props.onBeforeSubmit();
      const result = await api<GenerationJob>("/api/generations", { method: "POST", body: JSON.stringify(request) });
      setLatestJob(result);
      props.onChange({ last_job_id: result.id, pending_request_id: undefined, pending_submission: undefined });
      await props.onBeforeSubmit();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) {
        props.onChange({ pending_request_id: undefined, pending_submission: undefined });
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function cancel() {
    if (!job || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    const stop = (interrupt_running: boolean) => api<GenerationJob>(`/api/generations/${job.id}/cancel`, { method: "POST", body: JSON.stringify({ interrupt_running }) });
    try {
      try {
        setLatestJob(await stop(false));
      } catch (e) {
        if (!(e instanceof ApiError) || (e.detail as { code?: string })?.code !== "generation_interrupt_confirmation") throw e;
        if (window.confirm(`确认中断当前${label}任务？`)) setLatestJob(await stop(true));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const selectedInput = pending?.references[0] ?? input;
  const submitLabel = pending ? "重新确认提交" : watermark ? "烧录水印" : `开始${label}`;
  return (
    <section className="video-composer nodrag nopan nowheel" aria-label={label} onPointerDown={e => e.stopPropagation()} onWheel={e => e.stopPropagation()}>
      <header><strong>{label}</strong><small className="video-local-mark">本地</small></header>
      {selectedInput ? (
        <div className="video-controls">
          <button type="button" className="video-control" onClick={() => props.onPreview(selectedInput.version_id)}>
            <Film size={15} /> {pending ? "已固定来源" : "上游视频"} · {selectedInput.title || "查看素材"}
          </button>
        </div>
      ) : <p className="video-notice">将上游视频卡片的输出连到此卡片。上游有结果后即可处理。</p>}
      {watermark ? <WatermarkFields options={mark} video={selectedInput?.version_id}
        mediaRevision={props.mediaRevisions[selectedInput?.version_id ?? ""] ?? 0}
        logo={pending?.references.find(ref => ref.media_type === "image") ?? props.logo}
        disabled={blocked} onPreview={props.onPreview} onBeginEdit={props.onBeginEdit}
        onChange={watermark_options => props.onChange({watermark_options})} /> : <div className="video-advanced">
        <div className="video-parameter-grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
          <label>{interpolate ? "补帧模式" : "放大模式"}
            <StudioSelect value={method?.id ?? ""} disabled={blocked} onChange={e => {
              const selected = methods.find(item => item.id === e.target.value);
              if (selected) {
                props.onBeginEdit();
                props.onChange({ enhance_options: { ...options, method: selected.id } });
              }
            }}>
              {!method && <option value="" disabled>选择模式</option>}
              {methods.map(item => {
                const ready = methodReady(item.id);
                return <option key={item.id} value={item.id} disabled={!ready}>{item.name}{!ready ? "（暂不可用）" : ""}</option>;
              })}
            </StudioSelect>
          </label>
          <label>{interpolate ? "帧率预设" : "分辨率预设"}
            <StudioSelect value={preset} disabled={blocked} onChange={e => setPreset(e.target.value)}>
              {interpolate ? fpsPresets.map(fps => <option key={fps} value={fps}>{fps} fps</option>) : resolutionPresets.map(({ width, height }) => (
                <option key={height} value={height}>{height === 2160 ? "4K" : `${height}p`} · {width} × {height}</option>
              ))}
              <option value="custom">自定义</option>
            </StudioSelect>
          </label>
          {interpolate ? (
            <label>目标帧率（fps）<input ref={primaryNumber} type="number" min={1} max={120} step={1} value={options.fps ?? ""} disabled={blocked} onFocus={props.onBeginEdit} onChange={e => setNumber("fps", e.target.value)} /></label>
          ) : <>
            <label>目标宽度（像素）<input ref={primaryNumber} type="number" min={64} max={4096} step={2} value={options.width ?? ""} disabled={blocked} onFocus={props.onBeginEdit} onChange={e => setNumber("width", e.target.value)} /></label>
            <label>目标高度（像素）<input type="number" min={64} max={4096} step={2} value={options.height ?? ""} disabled={blocked} onFocus={props.onBeginEdit} onChange={e => setNumber("height", e.target.value)} /></label>
          </>}
          {rife && <label>镜头切点（可选）<input type="text" value={cutText} placeholder="例如 148, 322, 506" disabled={blocked} onFocus={props.onBeginEdit} onChange={e => updateCuts(e.target.value)} /></label>}
        </div>
        <p>{method?.description} {interpolate ? "目标帧率需达到源视频帧率。" : "按原画幅缩放，画幅不同时填边。"}</p>
        {rife && <p>切点使用每个新镜头在源视频中的首帧索引，从 0 开始计数。各切点以逗号或空格分隔。</p>}
        {!profile && <p role="status">{profileError ? "暂未读取本地模式状态。" : "正在检查本地模式…"}</p>}
      </div>}
      <footer className="video-controls">
        {job && <span className="video-output-count">{generationStateLabels[job.status]}</span>}
        <span className="video-control-spacer" />
        {active && job?.can_cancel ? (
          <button type="button" className="video-control video-cancel" title={`取消${label}`} aria-label={`取消${label}`} disabled={busy} onClick={() => void cancel()}><Square size={17} /></button>
        ) : (
          <button type="button" className="video-submit" title={submitLabel} aria-label={submitLabel} disabled={props.locked || busy || active || (!pending && (!input || !!invalid))} onClick={() => void submit()}>
            {busy || active ? <LoaderCircle className="spin" size={18} /> : <ArrowUp size={20} />}
          </button>
        )}
      </footer>
      <GenerationProgress job={job} pending={busy && !!pending} compact />
      {(error || invalid) && <p className="video-notice" role="alert">{error || invalid}</p>}
      {pending && !busy && <p className="video-notice">提交记录已保存，可以用同一请求重新确认。</p>}
      {job?.error && !active && <p className="video-notice" role="alert">{typeof job.error === "string" ? job.error : job.error.message}</p>}
    </section>
  );
}

function WatermarkFields({options, video, logo, mediaRevision, disabled, onChange, onPreview, onBeginEdit}: {
  options: WatermarkOptions;
  video?: string;
  logo?: {version_id: string; title?: string};
  mediaRevision: number;
  disabled: boolean;
  onChange: (options: WatermarkOptions) => void;
  onPreview: (version: string) => void;
  onBeginEdit: () => void;
}) {
  const [overlay, setOverlay] = useState("");
  const [previewError, setPreviewError] = useState("");
  const ready = options.mode === "text" ? !!options.text.trim() : !!logo;
  const previewBody = video && ready ? JSON.stringify({video_version_id: video, logo_version_id: logo?.version_id, options}) : "";
  useEffect(() => {
    setOverlay("");
    setPreviewError("");
    if (!previewBody) return;
    const controller = new AbortController();
    let url = "";
    const timer = setTimeout(async () => {
      try {
        const reply = await fetch("/api/video/watermark/preview", {
          method: "POST", headers: {"Content-Type": "application/json"}, body: previewBody, signal: controller.signal,
        });
        if (!reply.ok) {
          const body = await reply.json();
          throw new ApiError(reply.status, body.detail);
        }
        const blob = await reply.blob();
        if (!controller.signal.aborted) {
          url = URL.createObjectURL(blob);
          setOverlay(url);
        }
      } catch (error) {
        if (!controller.signal.aborted) setPreviewError(error instanceof Error ? error.message : "水印预览失败。");
      }
    }, 250);
    return () => {
      controller.abort();
      clearTimeout(timer);
      if (url) URL.revokeObjectURL(url);
    };
  }, [previewBody]);

  const set = <K extends keyof WatermarkOptions>(key: K, value: WatermarkOptions[K]) => onChange({...options, [key]: value});
  return <div className="video-advanced">
    <div className="video-parameter-grid watermark-fields">
      <label>水印类型
        <StudioSelect value={options.mode} disabled={disabled} onChange={e => {onBeginEdit(); set("mode", e.target.value as WatermarkOptions["mode"]);}}>
          <option value="text">文字</option><option value="image">Logo 图片</option>
        </StudioSelect>
      </label>
      <label>位置
        <StudioSelect value={options.position} disabled={disabled} onChange={e => {onBeginEdit(); set("position", e.target.value as WatermarkOptions["position"]);}}>
          <option value="top-left">左上</option><option value="top-right">右上</option>
          <option value="bottom-left">左下</option><option value="bottom-right">右下</option><option value="center">居中</option>
        </StudioSelect>
      </label>
      {options.mode === "text" ? <>
        <label className="watermark-wide">水印文字<input maxLength={100} value={options.text} disabled={disabled}
          placeholder="输入署名或账号" onFocus={onBeginEdit} onChange={e => set("text", e.target.value)} /></label>
        <label>文字颜色<input type="color" value={options.color} disabled={disabled} onFocus={onBeginEdit} onChange={e => set("color", e.target.value)} /></label>
      </> : logo ? <button className="video-control watermark-wide" type="button" onClick={() => onPreview(logo.version_id)}>Logo · {logo.title || "查看图片"}</button> : null}
      <label>大小（短边 {options.size}%）
        <input type="range" min={1} max={40} value={options.size} disabled={disabled} onFocus={onBeginEdit} onChange={e => set("size", Number(e.target.value))} />
      </label>
      <label>不透明度（{options.opacity}%）
        <input type="range" min={1} max={100} value={options.opacity} disabled={disabled} onFocus={onBeginEdit} onChange={e => set("opacity", Number(e.target.value))} />
      </label>
    </div>
    {video && <div className="watermark-preview" aria-label="水印预览">
      <img src={`${mediaUrl(video)}&refresh=${mediaRevision}`} alt="视频首帧" draggable={false} />
      {overlay && <img className="watermark-overlay" src={overlay} alt="水印" draggable={false} />}
    </div>}
    {previewError && <p role="alert">{previewError}</p>}
  </div>;
}
