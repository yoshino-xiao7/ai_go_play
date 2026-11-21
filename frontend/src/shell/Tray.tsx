import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronUp, RefreshCw } from "lucide-react";
import { api, dateText, mediaUrl } from "../api";
import type { Task } from "../types";
import type { GenerationJob } from "../generationTypes";
import { activeGenerationStates } from "../generationTypes";
import { EmptyState, Loading } from "../ui";
import { requestRounds } from "./roundsIntent";

const GenerationTasks = lazy(() => import("../GenerationTasks"));

/** Bucket → label. The order is the life of a job: workbench, engine queue, running, done, attention. */
const buckets = [
  { id: "wait", label: "工作台待发送", states: ["pending", "submitting"] },
  { id: "queue", label: "引擎排队", states: ["queued"] },
  { id: "run", label: "运行", states: ["running", "collecting"] },
  { id: "done", label: "完成", states: ["succeeded"] },
  { id: "attention", label: "需处理", states: ["failed", "unknown"] },
] as const;
const chipState: Record<GenerationJob["status"], { label: string; tone: string }> = {
  pending: { label: "待发送", tone: "wait" },
  submitting: { label: "提交中", tone: "wait" },
  queued: { label: "排队", tone: "queue" },
  running: { label: "运行", tone: "run" },
  collecting: { label: "保存", tone: "run" },
  succeeded: { label: "完成", tone: "done" },
  failed: { label: "失败", tone: "bad" },
  cancelled: { label: "已取消", tone: "off" },
  unknown: { label: "待核对", tone: "warn" },
};
const mediaStates: Record<string, string> = {
  pending: "等待处理", queued: "等待处理", running: "处理中", completed: "已完成", ready: "已完成", done: "已完成", failed: "失败", cancelled: "已取消",
};

type Props = {
  open: boolean;
  onToggle: (open: boolean) => void;
  currentProjectId: string | null;
  refresh: number;
  notify: (message: string, error?: boolean) => void;
  onActiveChange?: (count: number) => void;
};

/**
 * 显影槽: the global generation strip. Reads the real job list; nothing here submits a job.
 * A chip opens that card's result rounds in its project (the canvas consumes the intent).
 */
export default function Tray({ open, onToggle, currentProjectId, refresh, notify, onActiveChange }: Props) {
  const [jobs, setJobs] = useState<GenerationJob[] | null>(null);
  const [tab, setTab] = useState<"generation" | "media">("generation");
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [failed, setFailed] = useState(false);
  const seen = useRef(new Map<string, string>());
  const [flashed, setFlashed] = useState<Record<string, number>>({});

  const load = useCallback(async () => {
    try {
      const response = await api<{ items: GenerationJob[] }>("/api/generations?limit=40", { signal: AbortSignal.timeout(7000) });
      const changed: Record<string, number> = {};
      for (const job of response.items) {
        const before = seen.current.get(job.id);
        if (before && before !== job.status) changed[job.id] = Date.now();
        seen.current.set(job.id, job.status);
      }
      if (Object.keys(changed).length) setFlashed(current => ({ ...current, ...changed }));
      setJobs(response.items);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  const active = useMemo(() => (jobs || []).filter(job => activeGenerationStates.has(job.status)).length, [jobs]);
  useEffect(() => { onActiveChange?.(active); }, [active, onActiveChange]);

  useEffect(() => {
    void load();
    const listener = (event: Event) => {
      const type = String((event as CustomEvent).detail?.type || "");
      if (type.startsWith("generation.")) void load();
    };
    window.addEventListener("manju:event", listener);
    window.addEventListener("manju:reconnected", load);
    return () => { window.removeEventListener("manju:event", listener); window.removeEventListener("manju:reconnected", load); };
  }, [load, refresh]);
  useEffect(() => { // events are primary; poll slowly as a fallback, faster while something runs
    const timer = setInterval(() => void load(), active ? 2500 : 15000);
    return () => clearInterval(timer);
  }, [active, load]);

  const loadTasks = useCallback(() => api<Task[]>("/api/tasks").then(setTasks).catch(error => notify(error.message, true)), [notify]);
  useEffect(() => {
    if (!open || tab !== "media") return;
    void loadTasks();
    const timer = setInterval(() => void loadTasks(), 3000);
    return () => clearInterval(timer);
  }, [open, tab, loadTasks]);

  const counts = useMemo(() => Object.fromEntries(buckets.map(bucket => [bucket.id,
    (jobs || []).filter(job => (bucket.states as readonly string[]).includes(job.status)).length])), [jobs]);
  const recent = (jobs || []).slice(0, 14);

  const openJob = (job: GenerationJob) => {
    if (!job.source_node_id) { window.location.hash = `/canvas/${job.project_id}`; return; }
    requestRounds(job.project_id, job.source_node_id, job.outputs[0]?.version_id);
    if (currentProjectId !== job.project_id || !location.hash.startsWith(`#/canvas/${job.project_id}`) || location.hash.split("/").length > 3)
      window.location.hash = `/canvas/${job.project_id}`;
  };

  return (
    <section className={`tray ${open ? "is-open" : ""} ${active ? "is-live" : ""}`} aria-label="显影槽 · 生成任务">
      <div className="tray-bar">
        <button className="tray-title" onClick={() => onToggle(!open)} aria-expanded={open} title={open ? "收起显影槽" : "展开全部任务"}>
          <i>Developing</i><b>显影槽</b>
        </button>
        <div className="tray-counts" aria-label="任务计数">
          {buckets.map(bucket => <span key={bucket.id} className={`tray-count t-${bucket.id} ${counts[bucket.id] ? "has" : ""}`}>{bucket.label} <b>{counts[bucket.id] || 0}</b></span>)}
        </div>
        <div className="tray-chips" role="list">
          {failed && !jobs && <span className="tray-offline">本机服务暂不可达</span>}
          {jobs && !recent.length && <span className="tray-offline">还没有生成任务 · 在创作条写好描述后点「生成」</span>}
          {recent.map(job => {
            const state = chipState[job.status];
            const output = job.outputs[0]?.version_id;
            const kind = (job.request?.kind as string | undefined) || "image";
            return (
              <button role="listitem" key={job.id} className={`tray-chip tone-${state.tone} ${flashed[job.id] ? "is-flash" : ""}`}
                onAnimationEnd={() => setFlashed(current => { const next = { ...current }; delete next[job.id]; return next; })}
                onClick={() => openJob(job)} title={`${String(job.request?.prompt || "").slice(0, 80) || "生成任务"} · ${dateText(job.created_at)}`}>
                <span className="tray-thumb">{output && kind !== "audio" ? <img src={mediaUrl(output)} alt="" loading="lazy" /> : <span className={`tray-thumb-kind k-${kind}`} />}</span>
                <code>{job.id.slice(0, 6)}</code>
                <span className="tray-state"><i />{state.label}</span>
                {activeGenerationStates.has(job.status) && typeof job.progress === "number" && <span className="tray-progress" style={{ width: `${Math.round(job.progress * 100)}%` }} />}
              </button>
            );
          })}
        </div>
        <button className="tray-expand" onClick={() => onToggle(!open)} aria-label={open ? "收起任务面板" : "展开任务面板"}><ChevronUp size={16} /></button>
      </div>
      {open && (
        <div className="tray-body">
          <header className="tray-body-head">
            <div className="seg" role="tablist" aria-label="任务类别">
              <button role="tab" aria-selected={tab === "generation"} onClick={() => setTab("generation")}>生成任务</button>
              <button role="tab" aria-selected={tab === "media"} onClick={() => setTab("media")}>素材处理</button>
            </div>
            <span className="muted small">同一张卡片在引擎中一次只运行一轮；其余在工作台等待。</span>
          </header>
          <div className="tray-body-scroll">
            {tab === "generation" ? (
              <Suspense fallback={<Loading />}><GenerationTasks onOpenProject={id => { onToggle(false); window.location.hash = `/canvas/${id}`; }} /></Suspense>
            ) : tasks === null ? <Loading /> : !tasks.length ? (
              <EmptyState icon={<RefreshCw size={26} />} title="暂无素材处理任务" description="导入素材后，可以在这里查看预览处理状态。" />
            ) : (
              <div className="task-list">
                {tasks.map(task => (
                  <div className="task-row" key={task.id}>
                    <span className={`task-state ${task.status}`}>{mediaStates[task.status] || task.status}</span>
                    <div>
                      <strong>{task.message || ({ preview: "生成素材预览", migration: "迁移资料库", import: "导入素材" } as Record<string, string>)[task.kind || task.type || ""] || "素材处理"}</strong>
                      <small>{dateText(task.created_at)} · {task.id.slice(0, 8)}</small>
                      {task.error && <p className="error-text">{task.error}</p>}
                      {task.requires_file && <p className="muted small">请在素材库重新选择文件上传。</p>}
                    </div>
                    {task.status === "failed" && task.can_retry !== false && !task.requires_file && (
                      <button className="icon-button" aria-label="重试任务" onClick={async () => {
                        try { await api(`/api/tasks/${task.id}/retry`, { method: "POST" }); void loadTasks(); }
                        catch (error) { notify((error as Error).message, true); }
                      }}><RefreshCw size={16} /></button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
