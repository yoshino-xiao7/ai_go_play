import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Clapperboard, Cloud, Crosshair, HardDrive, History, ImagePlus, LoaderCircle, RefreshCw, RotateCcw, Shuffle, Star, X, CircleStop, Eye } from "lucide-react";
import { ApiError, api, mediaUrl } from "./api";
import type { GenerationJob, ImageHistoryItem } from "./generationTypes";
import { activeGenerationStates, generationStateLabels } from "./generationTypes";
import type { Workflow } from "./workflowTypes";
import { appendedTail, isCloudJob, roundChanges, roundsOf, snapshotOf } from "./roundSnapshots";
import "./generation-rounds.css";

export type RoundsNode = {
  id: string; title: string; kind: "image" | "video" | "audio"; locked: boolean;
  adoptedVersion?: string; history: ImageHistoryItem[];
  refillOf?: string; roundLinks?: Record<string, string>;
};

type Props = {
  projectId: string;
  node: RoundsNode;
  highlightVersion?: string;
  nodeTitles: Record<string, string>;
  onRefill: (job: GenerationJob, seed: "same" | "random") => void;
  onAdopt: (versionId: string) => void;
  onUseAsReference: (versionId: string, job: GenerationJob) => void;
  onToVideo: (versionId: string, job: GenerationJob) => void;
  onLocate: (nodeId: string, versionId?: string) => void;
  onPreview: (versionId: string) => void;
  onClose: () => void;
};

const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error);
const timeText = (value: string) => new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
const errorText = (job: GenerationJob) => typeof job.error === "string" ? job.error : job.error?.message || "";

/** Results of one canvas node, grouped by submission round. Reads only real job records. */
export default function GenerationRounds({ projectId, node, highlightVersion, nodeTitles, onRefill, onAdopt, onUseAsReference, onToVideo, onLocate, onPreview, onClose }: Props) {
  const [jobs, setJobs] = useState<GenerationJob[] | null>(null);
  const [workflows, setWorkflows] = useState<Record<string, Workflow>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const list = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);

  const refresh = useCallback(async () => {
    const mine = ++sequence.current;
    try {
      const response = await api<{ items: GenerationJob[] }>(`/api/generations?project_id=${encodeURIComponent(projectId)}`);
      if (mine === sequence.current) { setJobs(response.items); setError(""); }
    } catch (caught) { if (mine === sequence.current) setError(messageOf(caught)); }
  }, [projectId]);

  useEffect(() => {
    void refresh();
    void api<{ items: Workflow[] }>("/api/workflows").then(r => setWorkflows(Object.fromEntries(r.items.map(w => [w.id, w])))).catch(() => {});
    const listener = (event: Event) => {
      const payload = (event as CustomEvent).detail || {};
      if (payload.type === "generation.updated" && payload.data?.project_id === projectId) void refresh();
    };
    window.addEventListener("manju:event", listener);
    window.addEventListener("manju:reconnected", refresh);
    return () => { window.removeEventListener("manju:event", listener); window.removeEventListener("manju:reconnected", refresh); };
  }, [projectId, refresh]);

  const rounds = useMemo(() => roundsOf(jobs || [], node.id), [jobs, node.id]);
  const active = rounds.some(({ job }) => activeGenerationStates.has(job.status));
  useEffect(() => { // events are primary; a slow poll covers a lost socket while a round runs
    if (!active) return;
    const timer = setInterval(() => void refresh(), 1500);
    return () => clearInterval(timer);
  }, [active, refresh]);

  const highlightJob = highlightVersion ? rounds.find(({ job }) => job.outputs.some(o => o.version_id === highlightVersion))?.job.id : undefined;
  useEffect(() => {
    if (!highlightJob) return;
    requestAnimationFrame(() => list.current?.querySelector(`[data-round="${highlightJob}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" }));
  }, [highlightJob, rounds.length]);

  const operate = async (job: GenerationJob, operation: "cancel" | "retry") => {
    setBusy(job.id + operation); setError("");
    try {
      await api(`/api/generations/${job.id}/${operation}`, { method: "POST", body: JSON.stringify(operation === "cancel" ? { interrupt_running: false } : { request_id: crypto.randomUUID() }) });
      await refresh();
    } catch (caught) {
      // The server decides: a running job may need explicit interrupt confirmation, a node may already have an active job.
      setError(caught instanceof ApiError && (caught.detail as { code?: string })?.code === "generation_interrupt_confirmation"
        ? "这一轮正在运行。取消会中断生成，请在卡片的生成面板中确认中断。" : messageOf(caught));
    } finally { setBusy(""); }
  };

  const newestFirst = [...rounds].reverse();
  const byId = new Map(rounds.map(item => [item.job.id, item]));
  const kindLabel = node.kind === "video" ? "视频" : node.kind === "audio" ? "音频" : "图片";
  return (
    <aside className="gr-panel nodrag nopan nowheel" aria-label={`${node.title} 的结果轮次`}>
      <header className="gr-head">
        <div>
          <span className="gr-eyebrow"><History size={12} />结果轮次 · {kindLabel}</span>
          <h3 title={node.title}>{node.title}</h3>
        </div>
        <button className="gr-icon" onClick={() => onLocate(node.id)} title="在画布中定位此节点" aria-label="在画布中定位此节点"><Crosshair size={15} /></button>
        <button className="gr-icon" onClick={onClose} title="关闭" aria-label="关闭结果轮次"><X size={15} /></button>
      </header>
      <p className="gr-note">每一轮都是一次真实提交：提交时的描述、参数与参考版本由本机服务保存，回填只改卡片草稿，不改这些记录。</p>
      {error && <p className="gr-error" role="alert">{error}</p>}
      <div className="gr-list" ref={list}>
        {jobs === null && <p className="gr-empty"><LoaderCircle className="spin" size={14} />正在读取生成记录…</p>}
        {jobs !== null && !rounds.length && <p className="gr-empty">还没有提交过。写好描述后点“生成”，结果会按轮次出现在这里。</p>}
        {newestFirst.map(({ job, round }) => {
          const request = snapshotOf(job);
          const previous = rounds[round - 2]?.job;
          const changes = roundChanges(previous, job);
          const tail = appendedTail(previous && snapshotOf(previous).prompt, request.prompt || "");
          const prompt = request.prompt || "";
          const activeRound = activeGenerationStates.has(job.status);
          const cloud = isCloudJob(job);
          const workflow = request.workflow_id ? workflows[request.workflow_id] : undefined;
          const params = request.parameters || {};
          const link = node.roundLinks?.[job.id];
          const parent = job.parent_job_id ? byId.get(job.parent_job_id)?.round : undefined;
          return (
            <article key={job.id} data-round={job.id} className={`gr-round${job.id === highlightJob ? " is-highlight" : ""}${activeRound ? " is-active" : ""}`}>
              <div className="gr-round-head">
                <span className="gr-take">Take {round}</span>
                <span className={`gr-status s-${job.status}`}>{activeRound && <LoaderCircle className="spin" size={11} />}{generationStateLabels[job.status]}</span>
                <span className={`gr-where${cloud ? " cloud" : ""}`}>{cloud ? <><Cloud size={11} />云端</> : <><HardDrive size={11} />本机</>}</span>
                <time>{timeText(job.created_at)}</time>
              </div>
              {(link || parent || node.refillOf === job.id) && (
                <p className="gr-lineage">
                  {link && byId.get(link) && <>回填自 Take {byId.get(link)!.round}</>}
                  {parent && <>重试自 Take {parent}</>}
                  {node.refillOf === job.id && <span className="gr-draft-tag">当前草稿由此回填</span>}
                </p>
              )}
              <blockquote className="gr-prompt">{tail ? <>{prompt.slice(0, prompt.length - tail.length)}<mark>{tail}</mark></> : prompt || <em>（无描述）</em>}</blockquote>
              <div className="gr-meta">
                <span title={request.workflow_id}>{request.kind === "video" ? "H3 视频" : workflow?.name || request.workflow_id || "工作流"}</span>
                {params.width && params.height ? <span>{params.width}×{params.height}</span> : null}
                {request.kind === "video" && <span>{request.duration}s · {request.video_mode === "frames" ? "首尾帧" : request.video_mode === "reference" ? "全参考" : "文生"}{request.video_options?.engine && request.video_options.engine !== "native" ? ` · ${request.video_options.engine}` : ""}</span>}
                {params.seed !== undefined && <span>种子 {String(params.seed)}</span>}
                {params.steps !== undefined && <span>{String(params.steps)} 步</span>}
                {changes.map(change => <span key={change.key} className="gr-change">改 {change.label}</span>)}
              </div>
              {!!request.references?.length && (
                <ol className="gr-refs" aria-label="本轮参考（按引用顺序）">
                  {request.references.map((ref, index) => (
                    <li key={ref.version_id + index}>
                      <button type="button" disabled={!ref.node_id || !nodeTitles[ref.node_id]} onClick={() => ref.node_id && onLocate(ref.node_id, ref.version_id)}
                        title={ref.node_id && nodeTitles[ref.node_id] ? `定位来源：${nodeTitles[ref.node_id]}` : "来源节点已不在画布上"}>
                        <img src={mediaUrl(ref.version_id)} alt="" loading="lazy" />
                        <span>@{index + 1} {ref.title || "参考"}{ref.role === "first_frame" ? " · 首帧" : ref.role === "last_frame" ? " · 尾帧" : ""}</span>
                        <code>{ref.version_id.slice(0, 6)}</code>
                      </button>
                    </li>
                  ))}
                </ol>
              )}
              {job.status === "failed" && errorText(job) && <p className="gr-fail">{errorText(job)}</p>}
              {job.status === "unknown" && <p className="gr-fail">提交状态待核对：ComfyUI 可能仍在运行原任务。请在卡片的生成面板核对后再决定。</p>}
              {job.outputs.length > 0 && (
                <div className="gr-outputs">
                  {job.outputs.map(output => {
                    const adopted = output.version_id === node.adoptedVersion;
                    const here = !output.node_id || output.node_id === node.id;
                    const candidate = node.history.find(item => item.version_id === output.version_id)?.candidate;
                    return (
                      <figure key={output.version_id} className={`gr-output${adopted ? " is-adopted" : ""}${output.version_id === highlightVersion ? " is-highlight" : ""}`}>
                        <button type="button" className="gr-thumb" onClick={() => onPreview(output.version_id)} aria-label="预览结果">
                          {node.kind === "audio" ? <span className="gr-audio">音频结果</span> : <img src={mediaUrl(output.version_id)} alt="" loading="lazy" />}
                          <span className="gr-badge">{adopted ? <><Star size={10} />已采用</> : candidate ? "候选" : here ? "历史" : "另存节点"}</span>
                        </button>
                        <figcaption>
                          {here ? <button type="button" disabled={node.locked || adopted} onClick={() => onAdopt(output.version_id)}><Star size={12} />{adopted ? "已采用" : "采用"}</button>
                            : <button type="button" onClick={() => output.node_id && onLocate(output.node_id, output.version_id)}><ArrowUpRight size={12} />去结果卡片</button>}
                          {node.kind === "image" && <button type="button" onClick={() => onUseAsReference(output.version_id, job)}><ImagePlus size={12} />作参考</button>}
                          {node.kind === "image" && <button type="button" onClick={() => onToVideo(output.version_id, job)}><Clapperboard size={12} />转视频</button>}
                          <button type="button" onClick={() => onPreview(output.version_id)} aria-label="查看大图"><Eye size={12} /></button>
                        </figcaption>
                      </figure>
                    );
                  })}
                </div>
              )}
              <footer className="gr-actions">
                <button type="button" className="gr-primary" disabled={node.locked} onClick={() => onRefill(job, "same")} title="把这一轮的描述、参数、参考版本复制到卡片草稿（沿用当时的种子），不会提交"><RotateCcw size={12} />回填再改</button>
                <button type="button" disabled={node.locked} onClick={() => onRefill(job, "random")} title="同样的描述、参数与参考，种子改为随机；需要你再点生成才会提交"><Shuffle size={12} />同参数换种子</button>
                {activeRound && job.can_cancel !== false && <button type="button" disabled={!!busy} onClick={() => void operate(job, "cancel")}><CircleStop size={12} />取消</button>}
                {(job.status === "failed" || job.status === "cancelled") && job.can_retry !== false && <button type="button" disabled={!!busy || node.locked} onClick={() => void operate(job, "retry")}><RefreshCw size={12} />重试</button>}
              </footer>
            </article>
          );
        })}
      </div>
    </aside>
  );
}
