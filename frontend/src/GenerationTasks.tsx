import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowDownToLine, ArrowUpRight, CheckCircle2, ChevronDown, ChevronRight, CircleStop, FileJson, Image, LoaderCircle, RefreshCw, Sparkles } from "lucide-react";
import { api, ApiError, mediaUrl } from "./api";
import { EmptyState } from "./ui";
import { generationStateLabels } from "./generationTypes";
import type { GenerationJob } from "./generationTypes";
import type { Workflow } from "./workflowTypes";
import VideoViewer from "./VideoViewer";
import {GenerationProgress} from "./GenerationProgress";

type JobRequest = {
  provider?: "openai";
  model?: string;
  quality?: string;
  upstream_request_id?: string;
  cost_estimate?: {output_usd:number};
  actual_cost?: {total_usd:number};
  kind?: "video" | "audio";
  prompt: string;
  negative_prompt?: string;
  references: { version_id: string; node_id?: string; snapshot?: { filename: string; hash: string } }[];
  parameters: Record<string, number>;
  resolved_parameters?: Record<string, number>;
  mask_version_id?: string;
};
type Job = Omit<GenerationJob, "error" | "request"> & {
  error?: { message?: string; code?: string; details?: unknown } | string | null;
  request: JobRequest;
  prompt: string;
  workflow_id: string;
  workflow_snapshot?: Workflow;
  mapped_graph?: unknown;
  logs?: { at: string; status: string; message: string }[];
  can_cancel: boolean;
  can_retry: boolean;
  parent_job_id?: string;
};

const messageOf = (value: unknown) => value instanceof Error ? value.message : String(value);
const errorOf = (value: Job["error"]) => typeof value === "string" ? value : value?.message;
const activeStates = new Set(["pending", "submitting", "queued", "running", "collecting", "unknown"]);

export default function GenerationTasks({ onOpenProject }: { onOpenProject: (id: string) => void }) {
  const [videoPreview,setVideoPreview]=useState<string>();
  const [previewKind,setPreviewKind]=useState<"video"|"audio">("video");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [details, setDetails] = useState<Record<string, Job>>({});
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState<"all" | "active" | "failed">("all");
  const mounted = useRef(true);
  const expandedRef = useRef(expanded);
  expandedRef.current = expanded;
  const retryKeys = useRef<Record<string, string>>({});
  useEffect(() => {
    mounted.current = true;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const response = await api<{ items: Job[] }>("/api/generations?limit=100", { signal: AbortSignal.timeout(7000) });
        if (disposed) return;
        setJobs(response.items); setLoading(false); setError("");
        const id = expandedRef.current;
        if (id) {
          const detail = await api<Job>(`/api/generations/${id}`, { signal: AbortSignal.timeout(7000) });
          if (!disposed) setDetails(current => ({ ...current, [id]: detail }));
        }
      } catch (caught) { if (!disposed) { setError(messageOf(caught)); setLoading(false); } }
      if (!disposed) timer = setTimeout(() => void poll(), 2500);
    };
    void poll();
    return () => { disposed = true; mounted.current = false; clearTimeout(timer); };
  }, []);
  const showDetails = async (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    try { const value = await api<Job>(`/api/generations/${id}`); if (mounted.current) setDetails(current => ({ ...current, [id]: value })); } catch (caught) { if (mounted.current) setError(messageOf(caught)); }
  };
  const act = async (job: Job, action: "cancel" | "retry", interrupt = false) => {
    setBusy(job.id); setError("");
    if (action === "retry") retryKeys.current[job.id] ||= crypto.randomUUID();
    try {
      const result = await api<Job>(`/api/generations/${job.id}/${action}`, { method: "POST", body: JSON.stringify(action === "cancel" ? { interrupt_running: interrupt } : { request_id: retryKeys.current[job.id] }) });
      if (!mounted.current) return;
      if (action === "retry") delete retryKeys.current[job.id];
      setJobs(current => [result, ...current.filter(item => item.id !== result.id)]);
      setDetails(current => ({ ...current, [result.id]: result }));
      if (action === "retry") setExpanded(result.id);
    } catch (caught) {
      if (!mounted.current) return;
      if (caught instanceof ApiError && (caught.detail as { code?: string })?.code === "generation_interrupt_confirmation" && window.confirm(job.request.provider==="openai"?"结束跟踪不会撤回 OpenAI 请求，原请求可能已计费。已核对平台用量并结束跟踪？":job.status==="unknown"?"结束本地跟踪不会撤回 ComfyUI 原任务。原任务可能仍在运行；核对后结束跟踪？":"任务已经开始生成。确认中断这一个任务？")) { await act(job, action, true); return; }
      setError(messageOf(caught));
    } finally { if (mounted.current) setBusy(""); }
  };
  const exportAudit = async (id: string) => {
    try {
      const job = await api<Job>(`/api/generations/${id}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(job, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `generation-${id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) { setError(messageOf(caught)); }
  };
  const filtered = jobs.filter(job => filter === "all" || (filter === "active" ? activeStates.has(job.status) : job.status === "failed"));
  return <div className="generation-task-list">
    {videoPreview&&<VideoViewer kind={previewKind} versionId={videoPreview} onClose={()=>setVideoPreview(undefined)}/>}
    <div className="generation-task-filters">{([['all', '全部生成'], ['active', '进行中'], ['failed', '失败']] as const).map(([value, label]) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{label}</button>)}<span>最近 100 条 · 自动更新</span></div>
    {error && <p className="generation-task-error" role="alert"><AlertCircle size={15} />{error}</p>}
    {loading ? <div className="loading"><LoaderCircle className="spin" size={20} />读取生成记录</div> : filtered.length === 0 ? <EmptyState icon={<Sparkles size={28} />} title={filter === "all" ? "还没有生成记录" : "没有符合条件的任务"} description="在画布新建图片、视频或人物配音卡，填写描述后即可开始。" /> : filtered.map(job => {
      const detail = details[job.id];
      const request = detail?.request || job.request;
      const failedMessage = errorOf(job.error);
      const retryActive = jobs.some(item => item.parent_job_id === job.id && activeStates.has(item.status));
      return <article className={`generation-task-row ${job.status}`} key={job.id}>
        <div className="generation-task-summary"><div className="generation-task-icon">{job.status === "succeeded" ? <CheckCircle2 size={19} /> : activeStates.has(job.status) ? <LoaderCircle size={19} className="spin" /> : <Image size={19} />}</div><button className="generation-task-title" onClick={() => void showDetails(job.id)}><strong>{job.prompt || request.prompt}</strong><span>{request.kind === "video" ? "视频" : request.kind === "audio" ? "配音" : "图片"} · {generationStateLabels[job.status]} · {new Date(job.created_at).toLocaleString("zh-CN")} · {job.id.slice(0, 8)}</span></button><button className="icon-button" aria-label="查看生成详情" onClick={() => void showDetails(job.id)}>{expanded === job.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button></div>
        <GenerationProgress job={job} compact/>
        {job.outputs.length > 0 && <div className="generation-task-outputs">{job.outputs.map(output => <button key={output.version_id} title={request.kind==="video"?"播放生成视频":request.kind==="audio"?"播放生成配音":"在画布查看生成结果"} onClick={() => (request.kind==="video"||request.kind==="audio")?(()=>{setPreviewKind(request.kind);setVideoPreview(output.version_id);})():onOpenProject(job.project_id)}><img src={mediaUrl(output.version_id,request.kind==="audio"?"waveform":"thumbnail")} alt={request.kind==="video"?"生成视频":request.kind==="audio"?"生成配音":"生成图片"} loading="lazy" /></button>)}</div>}
        {failedMessage && <p className="generation-task-error"><AlertCircle size={14} />{failedMessage}</p>}
        <div className="generation-task-actions"><span>{job.message}</span>{job.can_cancel && <button disabled={busy === job.id} onClick={() => void act(job, "cancel")}><CircleStop size={13} />{job.status==="unknown"?"结束跟踪":"取消"}</button>}{job.can_retry && <button disabled={busy === job.id || retryActive} onClick={() => void act(job, "retry")}><RefreshCw size={13} />{retryActive ? "重试中" : "重试"}</button>}{job.outputs.map((output, index) => <a key={output.version_id} href={mediaUrl(output.version_id, "original", true)} download><ArrowDownToLine size={13}/>下载素材{job.outputs.length > 1 ? ` ${index + 1}` : ""}</a>)}<button onClick={() => onOpenProject(job.project_id)}>打开画布<ArrowUpRight size={13} /></button></div>
        {expanded === job.id && <div className="generation-task-details">{!detail ? <p className="muted small">读取记录中…</p> : <><dl><dt>使用的工作流</dt><dd>{detail.workflow_snapshot?.name || detail.workflow_id} · 修订 {detail.workflow_snapshot?.revision}</dd><dt>实际参数</dt><dd>{Object.entries(request.resolved_parameters || request.parameters).map(([key, value]) => `${key}=${value}`).join(" · ")}</dd><dt>{request.provider==="openai"?"OpenAI 请求":"ComfyUI 任务"}</dt><dd>{request.provider==="openai"?request.upstream_request_id || "尚未收到请求回执":detail.prompt_id || "尚未提交"}</dd></dl>{request.provider==="openai"&&<div className="generation-task-openai">模型：{request.model} · 画质：{request.quality}<br/>提交前图片输出预估：{request.cost_estimate?`$${request.cost_estimate.output_usd.toFixed(5)} + 输入费用`:"—"}<br/>按返回用量计算：{request.actual_cost?`$${request.actual_cost.total_usd.toFixed(5)}`:"未收到完整计费用量"}</div>}<div className="generation-task-inputs"><strong>实际传入的素材 · {request.references.length} 个</strong><div>{request.references.map((reference, index) => <span key={`${reference.version_id}-${index}`} title={reference.snapshot?.filename || reference.version_id}><img src={mediaUrl(reference.version_id)} alt={`参考素材 ${index + 1}`} /><small>素材 {index + 1} · {reference.snapshot?.filename || reference.version_id.slice(0, 8)}</small></span>)}{request.mask_version_id && <span><img src={mediaUrl(request.mask_version_id)} alt="编辑蒙版" /><small>编辑蒙版</small></span>}</div></div>{detail.error && typeof detail.error !== "string" && detail.error.details !== undefined && <details className="generation-task-diagnostics"><summary>查看执行错误</summary><pre>{JSON.stringify(detail.error.details, null, 2)}</pre></details>}<div className="generation-task-log">{detail.logs?.map((entry, index) => <p key={index}><time>{new Date(entry.at).toLocaleTimeString("zh-CN")}</time>{entry.message}</p>)}</div><button className="generation-audit-download" onClick={() => void exportAudit(job.id)}><FileJson size={14} />导出完整生成记录<ArrowDownToLine size={13} /></button></>}</div>}
      </article>;
    })}
  </div>;
}
