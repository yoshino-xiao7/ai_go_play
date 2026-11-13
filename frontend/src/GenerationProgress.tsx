import {useCallback, useSyncExternalStore} from "react";
import {api} from "./api";
import {activeGenerationStates, generationStateLabels, VIDEO_WATERMARK_WORKFLOW} from "./generationTypes";
import type {GenerationJob} from "./generationTypes";
import "./generation-progress.css";

type Entry = {job?: GenerationJob; listeners: Set<()=>void>; timer?: ReturnType<typeof setTimeout>; controller?: AbortController};
const jobs = new Map<string, Entry>();
const active = (job: GenerationJob) => activeGenerationStates.has(job.status) || job.status === "unknown";
function subscribe(id: string | undefined, listener: ()=>void) {
  if (!id) return ()=>{};
  let entry = jobs.get(id);
  if (!entry) {entry = {listeners:new Set()}; jobs.set(id, entry);}
  const current = entry;
  current.listeners.add(listener);
  async function poll() {
    current.timer = undefined;
    const controller = current.controller = new AbortController();
    try {
      const result = await api<GenerationJob>(`/api/generations/${id}`, {signal:controller.signal});
      if (!controller.signal.aborted) current.job = result;
    } catch {
      if (!controller.signal.aborted && current.job) current.job = {...current.job, execution_progress:{source:"comfyui",connected:false}};
    } finally {
      if (!controller.signal.aborted) {
        current.controller = undefined;
        current.listeners.forEach(notify=>notify());
        if (current.listeners.size && (!current.job || active(current.job))) current.timer = setTimeout(()=>void poll(), 1200);
      }
    }
  }
  if (!current.controller && !current.timer && (!current.job || active(current.job))) void poll();
  return ()=>{
    current.listeners.delete(listener);
    if (!current.listeners.size) {
      clearTimeout(current.timer);current.controller?.abort();jobs.delete(id);
    }
  };
}
// Multiple cards/panels sharing a job share one request; terminal jobs stop polling.
export function useGenerationJob(id?: string) {
  const listen = useCallback((listener:()=>void)=>subscribe(id,listener),[id]);
  return useSyncExternalStore(listen, ()=>id?jobs.get(id)?.job:undefined);
}

export function GenerationProgress({job, pending=false, compact=false}: {job?:GenerationJob;pending?:boolean;compact?:boolean}) {
  if (!pending && (!job || !active(job))) return null;
  const execution = job?.execution_progress;
  const running = !pending && job?.status === "running";
  const watermark = job?.request?.workflow_id === VIDEO_WATERMARK_WORKFLOW;
  const watermarkPercent = running && watermark && typeof job?.progress === "number" ? Math.floor(job.progress * 100) : undefined;
  const measured = running && execution?.connected && execution.value !== undefined && execution.max !== undefined && execution.max > 1;
  const percent = watermarkPercent ?? (measured ? Math.min(100,Math.max(0, Math.floor(execution.value! / execution.max! * 100))) : undefined);
  const videoFrames = execution?.node_type === "ManjuVideoEnhance";
  const label = pending ? "正在提交" : running && watermark ? job.message || "正在烧录水印" : running && videoFrames ? measured ? (execution.value === execution.max ? "正在收尾编码" : "正在处理视频帧") : "正在准备视频后期" : running && job?.request?.provider==="openai" ? "OpenAI 正在生成 · 完成后自动保存" : running ? execution?.connected ? execution.label || "等待执行进度" : "正在生成 · 连接进度通道中" : job ? generationStateLabels[job.status] : "正在提交";
  const sampling = execution?.node_type?.includes("Sampler") || execution?.node_type==="MiniMaxH3Director";
  return <div className={compact?"generation-live-inline":"generation-live-overlay"} role="status" aria-label="生成进度">
    {!compact && <div className="generation-live-dots" aria-hidden="true"/>}
    <div className="generation-live-detail"><span>{label}</span>{measured && <strong>{execution!.value} / {execution!.max}{videoFrames ? " 帧" : sampling ? " 步" : ""}<small>{percent}%</small></strong>}
      {watermarkPercent !== undefined && <strong>{watermarkPercent}%</strong>}
      {percent !== undefined && <div className="generation-live-track" role="progressbar" aria-label={watermark ? "水印烧录进度" : videoFrames ? "视频帧处理进度" : "当前步骤进度"} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><i style={{width:`${percent}%`}}/></div>}
      {!compact && <small>{measured?"当前步骤进度 · 完成后自动保存":"结果将保留在当前卡片"}</small>}
    </div>
  </div>;
}
