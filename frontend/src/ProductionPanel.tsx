import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Check, CheckCircle2, Clapperboard, Download, Film, FolderDown, LoaderCircle, MapPin, Music2, Play, Plus, RefreshCw, Save, Sparkles, Trash2, X } from "lucide-react";
import { api, ApiError, mediaUrl } from "./api";
import { Modal } from "./ui";
import StudioSelect from "./StudioSelect";
import type { Asset, AssetPage, AssetVersion, CanvasData } from "./types";
import { activeGenerationStates, generationStateLabels, type GenerationJob } from "./generationTypes";
import { GenerationProgress } from "./GenerationProgress";
import ProductionPreview, { subtitleWindow } from "./ProductionPreview";
import type { ProductionDocument, ProductionRender, ProductionSettings, ProductionShot } from "./productionTypes";
import "./production.css";

type Props = { projectId: string; onClose: () => void; onChanged: () => void; onLocate?: (nodeId: string) => void };
type Choice = { key: string; title: string; kind: "video" | "audio"; versionId?: string; nodeId?: string; duration?: number | null; missing?: boolean };
type Issue = { shotId?: string; message: string };
type Draft = { revision: number; shots: ProductionShot[]; settings: ProductionSettings; saved_at: number };
type BatchResult = { jobs?: (GenerationJob | { id?: string; job_id?: string; status?: string })[]; skipped?: unknown[]; errors?: unknown[] };
const message = (e: unknown): string => e instanceof Error ? e.message : typeof e === "string" ? e : e && typeof e === "object" && "message" in e ? String(e.message) : JSON.stringify(e);
const seconds = (n: number) => `${Number(n.toFixed(2))} 秒`;
const timecode = (n: number) => `${Math.floor(n / 60).toString().padStart(2, "0")}:${(n % 60).toFixed(1).padStart(4, "0")}`;
const activeRender = (render?: ProductionRender) => !!render && ["pending", "running"].includes(render.status);
const initialSettings: ProductionSettings = { width: 1280, height: 720, fps: 24, background_volume: 0.15 };
const draftKey = (id: string) => `manju:production-draft:${id}`;
const newShot = (order: number): ProductionShot => ({ id: crypto.randomUUID(), order, title: `镜头 ${String(order).padStart(2, "0")}`, scene: "", characters: [], dialogue: "", speaker: "", duration: 5, trim_start: 0, audio_offset: 0, video_volume: 0, audio_volume: 1, status: "draft", notes: "" });

function downloadJson(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ProductionPanel({ projectId, onClose, onChanged, onLocate }: Props) {
  const [document, setDocument] = useState<ProductionDocument>(), [shots, setShots] = useState<ProductionShot[]>([]), [settings, setSettings] = useState<ProductionSettings>(initialSettings);
  const [selectedId, setSelectedId] = useState(""), [canvas, setCanvas] = useState<CanvasData>(), [assets, setAssets] = useState<Asset[]>([]), [versions, setVersions] = useState<Record<string, AssetVersion>>({});
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(""), [dirty, setDirty] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [issues, setIssues] = useState<Issue[] | null>(null), [previewShots, setPreviewShots] = useState<ProductionShot[] | null>(null), [recoverable, setRecoverable] = useState<Draft>();
  const [render, setRender] = useState<ProductionRender>(), [showOutput, setShowOutput] = useState(false), [settingsOpen, setSettingsOpen] = useState(false);
  const [batch, setBatch] = useState<BatchResult>();
  const [generationJobs, setGenerationJobs] = useState<GenerationJob[]>([]), [generationError, setGenerationError] = useState("");
  const alive = useRef(true), dirtyRef = useRef(dirty), currentRef = useRef({ shots, settings, document });
  dirtyRef.current = dirty; currentRef.current = { shots, settings, document };
  const saveRequest = useRef<{ fingerprint: string; payload: Record<string, unknown> } | undefined>(undefined), renderRequest = useRef<{ fingerprint: string; requestId: string } | undefined>(undefined);
  const batchRequest = useRef<{ fingerprint: string; requestId: string } | undefined>(undefined);
  const onChangedRef = useRef(onChanged); onChangedRef.current = onChanged;
  const completed = useRef(new Set<string>());
  const recoveryStorageKey = useRef(draftKey(projectId));
  const base = `/api/projects/${encodeURIComponent(projectId)}/production`;

  const loadMedia = useCallback(async () => {
    const [nextCanvas, first] = await Promise.all([api<CanvasData>(`/api/projects/${projectId}/canvas`), api<AssetPage>(`/api/assets?project_id=${projectId}&limit=500`)]);
    const nextAssets = [...first.items];
    for (let offset = 500; offset < first.total; offset += 500) nextAssets.push(...(await api<AssetPage>(`/api/assets?project_id=${projectId}&limit=500&offset=${offset}`)).items);
    if (alive.current) { setCanvas(nextCanvas); setAssets(nextAssets); setVersions(current => ({ ...current, ...Object.fromEntries(nextAssets.map(asset => [asset.version.id, asset.version])) })); }
  }, [projectId]);
  const load = useCallback(async (preserveEdits = false) => {
    const result = await api<ProductionDocument>(base);
    if (!alive.current || preserveEdits && (dirtyRef.current || result.revision < (currentRef.current.document?.revision || 0))) return;
    setDocument(result); setShots(result.shots || []); setSettings({ ...initialSettings, ...result.settings }); setDirty(false); setSelectedId(current => result.shots.some(shot => shot.id === current) ? current : result.shots[0]?.id || "");
    setRender(result.renders?.find(item => activeRender(item)) || result.renders?.[0]);
  }, [base]);
  useEffect(() => {
    alive.current = true;
    try {
      const prefix = draftKey(projectId), keys = [prefix];
      for (let index = 0; index < localStorage.length; index++) { const key = localStorage.key(index); if (key?.startsWith(prefix + ":backup:")) keys.push(key); }
      const drafts = keys.flatMap(key => { try { const saved = JSON.parse(localStorage.getItem(key) || "null"); return saved && Array.isArray(saved.shots) && saved.settings ? [{key,saved:saved as Draft}] : []; } catch { return []; } });
      drafts.sort((a,b) => a.key === prefix ? -1 : b.key === prefix ? 1 : b.saved.saved_at-a.saved.saved_at);
      if (drafts[0]) { recoveryStorageKey.current = drafts[0].key; setRecoverable(drafts[0].saved); }
    } catch { /* Old or incomplete drafts are ignored. */ }
    void Promise.all([load(), loadMedia()]).catch(e => { if (alive.current) setError(message(e)); }).finally(() => { if (alive.current) setLoading(false); });
    return () => { alive.current = false; };
  }, [projectId, load, loadMedia]);
  useEffect(() => {
    let disposed = false, timer: ReturnType<typeof setTimeout>, lastResults = "", ticks = 0;
    const poll = async () => {
      try {
        const result = await api<{ items: GenerationJob[] }>(`/api/generations?project_id=${encodeURIComponent(projectId)}&limit=500`, { signal: AbortSignal.timeout(7000) });
        if (disposed) return;
        setGenerationJobs(result.items); setGenerationError("");
        const signature = JSON.stringify(result.items.map(job => [job.id, job.status, job.outputs]));
        // Read current source cards as jobs finish; fixed shot versions remain explicit choices.
        if (ticks++ > 0 && (signature !== lastResults || ticks % 4 === 0)) await Promise.all([loadMedia(), load(true)]);
        lastResults = signature;
      } catch { if (!disposed) setGenerationError("生成进度暂时无法连接，正在重试；已提交任务会继续运行。"); }
      if (!disposed) timer = setTimeout(() => void poll(), 2500);
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [projectId, load, loadMedia]);
  useEffect(() => {
    if (!dirty || !document) return;
    try { localStorage.setItem(draftKey(projectId), JSON.stringify({ shots, settings, revision: document.revision, saved_at: Date.now() })); }
    catch { setNotice("浏览器草稿空间不足，请保存分镜或下载草稿。"); }
  }, [shots, settings, dirty, document, projectId]);
  useEffect(() => {
    const ids = new Set(shots.flatMap(shot => [shot.video_version_id, shot.audio_version_id]).filter((id): id is string => !!id));
    if (settings.background_audio_version_id) ids.add(settings.background_audio_version_id);
    const missing = [...ids].filter(id => !versions[id]);
    if (!missing.length) return;
    let disposed = false;
    void Promise.allSettled(missing.map(async id => ({ id, value: await api<{ version: AssetVersion }>(`/api/versions/${id}`) }))).then(results => {
      if (disposed || !alive.current) return;
      const entries: Record<string, AssetVersion> = {};
      results.forEach((result, index) => { if (result.status === "fulfilled") entries[result.value.id] = result.value.value.version; else entries[missing[index]] = { id: missing[index], missing: true } as AssetVersion; });
      setVersions(current => ({ ...current, ...entries }));
    });
    return () => { disposed = true; };
  }, [shots, settings.background_audio_version_id, versions]);
  useEffect(() => {
    if (!render || !activeRender(render)) return;
    let disposed = false, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api<ProductionRender>(`/api/production/renders/${render.id}`);
        if (disposed || !alive.current) return;
        setRender(value);
        if (value.status === "succeeded" && !completed.current.has(value.id)) { completed.current.add(value.id); setNotice("成片已加入当前项目和资产库。"); onChangedRef.current(); void loadMedia(); if (!dirtyRef.current) void load(); }
      } catch (e) { if (!disposed && alive.current) setNotice(`成片状态读取暂时失败，任务仍保留：${message(e)}`); }
      if (!disposed) timer = setTimeout(() => void poll(), 1500);
    };
    timer = setTimeout(() => void poll(), 700);
    return () => { disposed = true; clearTimeout(timer); };
  }, [render?.id, render?.status, loadMedia, load]);
  const choices = useMemo<Choice[]>(() => {
    const result: Choice[] = [];
    for (const node of canvas?.nodes || []) {
      const data = node.data as { kind?: string; title?: string; asset_version_id?: string; generation?: { kind?: string } };
      const kind = data.kind || data.generation?.kind;
      if (node.type !== "media" || (kind !== "video" && kind !== "audio")) continue;
      result.push({ key: `node:${node.id}`, title: `画布 · ${data.title || (kind === "video" ? "视频卡" : "配音卡")}${data.asset_version_id ? "" : "（尚未生成）"}`, kind, nodeId: node.id, versionId: data.asset_version_id, duration: data.asset_version_id ? versions[data.asset_version_id]?.duration : undefined });
    }
    for (const asset of assets) if (asset.type === "video" || asset.type === "audio") result.push({ key: `version:${asset.current_version_id}`, title: `素材 · ${asset.name}`, kind: asset.type, versionId: asset.current_version_id, duration: asset.version.duration, missing: asset.version.missing });
    return result;
  }, [assets, canvas, versions]);
  const selected = shots.find(shot => shot.id === selectedId), total = shots.reduce((sum, shot) => sum + shot.duration, 0), ready = shots.filter(shot => shot.video_version_id).length;
  const latestJobs = useMemo(() => {
    const result = new Map<string, GenerationJob>();
    for (const job of generationJobs) if (job.source_node_id && !result.has(job.source_node_id)) result.set(job.source_node_id, job);
    return result;
  }, [generationJobs]);
  function shotJob(shot: ProductionShot, kind: "video" | "audio") { return latestJobs.get(shot[`${kind}_node_id`] || ""); }
  function jobCaption(shot: ProductionShot) {
    return (["video", "audio"] as const).flatMap(kind => {
      const job = shotJob(shot, kind);
      if (!job || job.status === "succeeded" || job.status === "cancelled") return [];
      return [`${kind === "video" ? "视频" : "配音"}${generationStateLabels[job.status]}`];
    }).join(" · ");
  }
  function generationStatus(shot: ProductionShot, kind: "video" | "audio") {
    const job = shotJob(shot, kind);
    if (!job) return null;
    const output = job.outputs[0];
    const adopted = output?.version_id === shot[`${kind}_version_id`];
    return <div className="production-generation-status">
      {activeGenerationStates.has(job.status) ? <GenerationProgress job={job} compact/> : <small className={job.status === "failed" ? "production-error" : "production-hint"}>{generationStateLabels[job.status]}{job.status === "succeeded" ? adopted ? " · 当前分镜已采用" : " · 结果已保存到资产库，待采用" : job.error ? ` · ${message(job.error)}` : ""}</small>}
      {output && <div className="production-source-actions">{!adopted && <button onClick={() => editShot(shot.id, { [`${kind}_version_id`]: output.version_id, status: "draft" })}><Check size={13}/>采用此次{kind === "video" ? "视频" : "配音"}结果</button>}<a href={mediaUrl(output.version_id, "original", true)} download><Download size={13}/>下载{kind === "video" ? "视频" : "配音"}</a></div>}
    </div>;
  }
  const editShot = (id: string, patch: Partial<ProductionShot>) => { setShots(current => current.map(shot => shot.id === id ? { ...shot, ...patch } : shot)); setDirty(true); setIssues(null); setError(""); };
  const editSettings = (patch: Partial<ProductionSettings>) => { setSettings(current => ({ ...current, ...patch })); setDirty(true); setIssues(null); };
  function addShot() { const shot = newShot(shots.length + 1); setShots([...shots, shot]); setSelectedId(shot.id); setDirty(true); setPreviewShots(null); }
  function reorder(index: number, movement: number) { const next = [...shots]; [next[index], next[index + movement]] = [next[index + movement], next[index]]; setShots(next.map((shot, order) => ({ ...shot, order: order + 1 }))); setDirty(true); setPreviewShots(null); }
  function chooseMedia(kind: "video" | "audio", value: string) {
    if (!selected) return;
    const choice = choices.find(item => item.key === value);
    editShot(selected.id, { [`${kind}_version_id`]: choice?.versionId || null, [`${kind}_node_id`]: choice?.nodeId || null, ...(kind === "video" ? { trim_start: 0 } : {}), status: "draft" });
  }
  function selectionKey(shot: ProductionShot, kind: "video" | "audio") { const node = shot[`${kind}_node_id`], version = shot[`${kind}_version_id`]; return node ? `node:${node}` : version ? `version:${version}` : ""; }
  function validate(scope = shots): Issue[] {
    const result: Issue[] = [];
    if (!scope.length) result.push({ message: "请先添加镜头。" });
    for (const shot of scope) {
      const prefix = `${String(shot.order).padStart(2, "0")} ${shot.title}`;
      if (!shot.video_version_id) result.push({ shotId: shot.id, message: `${prefix}：尚未采用视频。` });
      else if (versions[shot.video_version_id]?.missing) result.push({ shotId: shot.id, message: `${prefix}：视频原件缺失。` });
      if (!Number.isFinite(shot.duration) || shot.duration <= 0) result.push({ shotId: shot.id, message: `${prefix}：镜头时长必须大于 0。` });
      const duration = shot.video_version_id ? versions[shot.video_version_id]?.duration : null;
      if (duration && shot.trim_start + shot.duration > duration + .03) result.push({ shotId: shot.id, message: `${prefix}：视频剩余 ${seconds(Math.max(0, duration - shot.trim_start))}，短于设定镜头时长。` });
      const audioDuration = shot.audio_version_id ? versions[shot.audio_version_id]?.duration : null;
      if (shot.audio_version_id && versions[shot.audio_version_id]?.missing) result.push({ shotId: shot.id, message: `${prefix}：配音原件缺失。` });
      if (audioDuration && shot.audio_offset + audioDuration > shot.duration + .03) result.push({ shotId: shot.id, message: `${prefix}：配音加延迟为 ${seconds(shot.audio_offset + audioDuration)}，请加长镜头或重做配音。` });
      if (shot.audio_offset < 0 || shot.trim_start < 0) result.push({ shotId: shot.id, message: `${prefix}：裁剪起点和配音延迟不能为负数。` });
      if (shot.subtitle_start != null && (shot.subtitle_start < 0 || shot.subtitle_start >= shot.duration)) result.push({ shotId: shot.id, message: `${prefix}：字幕起点须在镜头内。` });
      if (shot.subtitle_end != null && (shot.subtitle_end > shot.duration || shot.subtitle_end <= subtitleWindow(shot).start)) result.push({ shotId: shot.id, message: `${prefix}：字幕终点须晚于起点且在镜头内。` });
    }
    if (settings.background_audio_version_id && versions[settings.background_audio_version_id]?.missing) result.push({ message: "背景音乐原件缺失。" });
    return result;
  }
  async function save(): Promise<ProductionDocument> {
    const current = currentRef.current;
    if (!current.document) throw new Error("分镜尚未读取完成。");
    if (!dirtyRef.current) return current.document;
    const fingerprint = JSON.stringify({ revision: current.document.revision, settings: current.settings, shots: current.shots });
    if (saveRequest.current?.fingerprint !== fingerprint) saveRequest.current = { fingerprint, payload: { revision: current.document.revision, settings: current.settings, shots: current.shots, request_id: crypto.randomUUID() } };
    const result = await api<ProductionDocument>(base, { method: "PUT", body: JSON.stringify(saveRequest.current.payload) });
    if (!alive.current) return result;
    saveRequest.current = undefined; setDocument(result); setShots(result.shots); setSettings({ ...initialSettings, ...result.settings }); setDirty(false); dirtyRef.current = false; currentRef.current = { document: result, shots: result.shots, settings: result.settings };
    localStorage.removeItem(draftKey(projectId)); setRecoverable(undefined); onChangedRef.current();
    return result;
  }
  async function action(name: string, fn: () => Promise<void>) { if (busy) return; setBusy(name); setError(""); setNotice(""); try { await fn(); } catch (e) { if (alive.current) setError(message(e)); } finally { if (alive.current) setBusy(""); } }
  async function startRender() {
    const found = validate(); setIssues(found); if (found.length) return;
    await action("render", async () => {
      const saved = await save(), fingerprint = JSON.stringify({ revision: saved.revision, settings: saved.settings, shots: saved.shots });
      if (renderRequest.current?.fingerprint !== fingerprint) renderRequest.current = { fingerprint, requestId: crypto.randomUUID() };
      const task = await api<ProductionRender>(`${base}/render`, { method: "POST", body: JSON.stringify({ revision: saved.revision, request_id: renderRequest.current.requestId, burn_subtitles: true }) });
      renderRequest.current = undefined; setRender(task); setShowOutput(false); setNotice("成片导出已开始，可以关闭面板，任务会继续运行。");
    });
  }
  async function generate(shot?: ProductionShot, kind?: "video" | "audio") {
    await action("generate", async () => {
      const saved = await save();
      const payload = { revision:saved.revision, ...(shot ? { shot_ids: [shot.id] } : {}), kinds: kind ? [kind] : ["video", "audio"], only_missing: !shot };
      const fingerprint = JSON.stringify(payload);
      if (batchRequest.current?.fingerprint !== fingerprint) batchRequest.current = { fingerprint, requestId: crypto.randomUUID() };
      const result = await api<BatchResult>(`${base}/generate`, { method: "POST", body: JSON.stringify({ ...payload, request_id: batchRequest.current.requestId }) });
      batchRequest.current = undefined;
      setBatch(result); setNotice(`已提交 ${result.jobs?.length || 0} 个任务；新结果入库后可在对应镜头中明确采用。`); onChangedRef.current();
      // Batch submission updates source-card job IDs and the shared canvas revision.
      await Promise.all([load(), loadMedia()]);
    });
  }
  function preview(scope: ProductionShot[]) { const found = validate(scope); setIssues(found.length ? found : null); if (!found.length) { setPreviewShots(scope.map(shot => ({ ...shot, audio_duration: shot.audio_version_id ? versions[shot.audio_version_id]?.duration : undefined }))); setShowOutput(false); setSettingsOpen(false); } }
  function restoreDraft() {
    if (!recoverable || !document) return;
    try { localStorage.setItem(`${draftKey(projectId)}:backup:${recoverable.saved_at || Date.now()}`,JSON.stringify(recoverable)); }
    catch { setError("备份保存失败，请先下载草稿后再恢复。"); return; }
    const current=currentRef.current.shots;
    const copies=recoverable.shots.map((shot,index)=>({...shot,id:crypto.randomUUID(),order:current.length+index+1,title:`${shot.title.slice(0,240)}（恢复副本）`,status:"draft" as const}));
    setShots([...current,...copies]);setSelectedId(copies[0]?.id||selectedId);setDirty(true);setIssues(null);setRecoverable(undefined);
    setNotice(`已追加 ${copies.length} 个分镜副本；当前镜头、成片设置和原始备份均已保留。`);
  }
  const downloadHandoff = (kind: "subtitles" | "handoff") => action(kind, async () => { await save(); const response = await fetch(`${base}/${kind}`); if (!response.ok) { const body = await response.json().catch(() => null); throw new ApiError(response.status, body?.detail || "导出失败"); } const url = URL.createObjectURL(await response.blob()); const anchor = window.document.createElement("a"); anchor.href = url; anchor.download = kind === "subtitles" ? "分镜字幕.srt" : "分镜剪辑交接.zip"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });

  return <Modal title="分镜与成片" className="production-modal" onClose={onClose} wide>
    <div className="production-summary"><div><Clapperboard size={20}/><strong>{shots.length} 个镜头</strong><span>{timecode(total)} · {ready}/{shots.length} 已采用视频</span><span className={dirty ? "production-unsaved" : "production-saved"}>{dirty ? "草稿已保留在本机" : "已保存"}</span></div><button disabled={!!busy || loading} onClick={() => void action("refresh", async () => { await loadMedia(); if (dirtyRef.current) { setNotice("素材列表已更新，当前未保存分镜已保留。"); } else { await load(); setNotice("分镜和素材已刷新。"); } })} title="刷新分镜与素材"><RefreshCw size={15}/></button></div>
    {error && <div className="production-banner production-error" role="alert"><span>{error}</span>{dirty && <><button onClick={() => downloadJson({ ...currentRef.current, saved_at: Date.now() }, "分镜草稿.json")}>下载草稿</button><button disabled={!!busy} onClick={() => void action("reload", async () => { const value: Draft = { revision: document?.revision || 0, shots, settings, saved_at: Date.now() }; localStorage.setItem(draftKey(projectId), JSON.stringify(value)); setRecoverable(value); await load(); setNotice("已加载最新分镜；旧草稿可用下方恢复入口取回。"); })}>保留草稿并加载最新</button></>}</div>}
    {notice && <div className="production-banner" role="status">{notice}</div>}
    {generationError && <div className="production-banner" role="status">{generationError}</div>}
    {recoverable && <div className="production-banner production-recovery"><span>发现本机分镜草稿（{recoverable.shots.length} 个镜头）。恢复会追加副本，保留当前镜头与成片设置。</span><button disabled={!!busy || loading} onClick={restoreDraft}>恢复为分镜副本</button><button onClick={() => downloadJson(recoverable, "分镜草稿.json")}>下载备份</button><button onClick={() => { localStorage.removeItem(recoveryStorageKey.current); setRecoverable(undefined); }}>丢弃备份</button></div>}
    {loading ? <div className="production-loading"><LoaderCircle className="spin"/>正在读取分镜与素材…</div> : <div className="production-body">
      <aside className="production-shot-list"><header><span>镜头顺序</span><button disabled={!!busy} onClick={addShot} aria-label="添加镜头"><Plus size={17}/></button></header>
        {!shots.length && <div className="production-list-empty"><Film size={30}/><p>把镜头、台词和声音放在一起。</p><button className="button secondary" onClick={addShot}>添加第一个镜头</button></div>}
        <ol>{shots.map((shot, index) => <li className={selectedId === shot.id ? "selected" : ""} key={shot.id}>
          <button className="production-shot-select" onClick={() => { setSelectedId(shot.id); setPreviewShots(null); setShowOutput(false); }}><span className="production-shot-number">{String(index + 1).padStart(2, "0")}</span><span className="production-shot-thumb">{shot.video_version_id ? <img src={mediaUrl(shot.video_version_id)} loading="lazy" alt=""/> : <Film size={20}/>}</span><span className="production-shot-caption"><strong>{shot.title}</strong><small>{seconds(shot.duration)} · {shot.status === "approved" ? "已验收" : shot.video_version_id ? "待验收" : "待生成"}</small>{jobCaption(shot) && <em>{jobCaption(shot)}</em>}{shot.stale && <em>源素材已更新</em>}</span></button>
          <div className="production-order-controls"><button aria-label={`上移镜头 ${index + 1}`} title="上移" disabled={!!busy || index === 0} onClick={() => reorder(index, -1)}><ArrowUp size={12}/></button><button aria-label={`下移镜头 ${index + 1}`} title="下移" disabled={!!busy || index === shots.length - 1} onClick={() => reorder(index, 1)}><ArrowDown size={12}/></button></div>
        </li>)}</ol>
        {!!shots.length && <button className="production-add-shot" disabled={!!busy} onClick={addShot}><Plus size={15}/>添加镜头</button>}
      </aside>
      <main className="production-editor">
        {showOutput && render?.output_version_id ? <section className="production-output"><header><strong>已导出成片</strong><button onClick={() => setShowOutput(false)} aria-label="关闭成片预览"><X size={17}/></button></header><video src={mediaUrl(render.output_version_id, "original")} controls autoPlay playsInline/><a className="button secondary" href={mediaUrl(render.output_version_id, "original", true)} download><Download size={15}/>下载成片 MP4</a></section> : previewShots ? <ProductionPreview key={previewShots.map(shot => shot.id).join(",")} shots={previewShots} settings={settings} onClose={() => setPreviewShots(null)}/> : selected ? <fieldset disabled={!!busy} className="production-shot-editor">
          <div className="production-editor-heading"><span>镜头 {String(shots.indexOf(selected) + 1).padStart(2, "0")}</span><div>{onLocate && <button title="在画布定位" onClick={() => onLocate(selected.id)}><MapPin size={15}/></button>}<button title="移除镜头（保留素材）" onClick={() => { const next = shots.filter(shot => shot.id !== selected.id).map((shot, index) => ({ ...shot, order: index + 1 })); setShots(next); setSelectedId(next[0]?.id || ""); setDirty(true); }}><Trash2 size={15}/></button></div></div>
          <label className="production-title-field"><span>镜头名称</span><input aria-label="镜头名称" value={selected.title} onChange={e => editShot(selected.id, { title: e.target.value })}/></label>
          <div className="production-fields two"><label><span>场景</span><input aria-label="镜头场景" placeholder="雨夜 · 街角" value={selected.scene} onChange={e => editShot(selected.id, { scene: e.target.value })}/></label><label><span>出场人物</span><input aria-label="出场人物" placeholder="用逗号分隔" value={selected.characters.join("，")} onChange={e => editShot(selected.id, { characters: e.target.value.split(/[,，]/) })} onBlur={e => editShot(selected.id, { characters: e.target.value.split(/[,，]/).map(value => value.trim()).filter(Boolean) })}/></label></div>
          <div className="production-fields two"><label><span>镜头时长（秒）</span><input type="number" aria-label="镜头时长" min={0.1} max={120} step={.1} value={selected.duration} onChange={e => editShot(selected.id, { duration: Number(e.target.value) })}/></label><label><span>验收状态</span><StudioSelect aria-label="镜头验收状态" value={selected.status} onChange={e => editShot(selected.id, { status: e.target.value as ProductionShot["status"] })}><option value="draft">草稿</option><option value="ready">素材就绪</option><option value="approved">已验收</option></StudioSelect></label></div>
          <section className="production-media-section"><header><Film size={16}/><strong>画面</strong>{selected.video_version_id && <button onClick={() => preview([selected])}><Play size={13}/>预览此镜</button>}</header>
            <label><span>采用视频 / 生成卡</span><StudioSelect aria-label="镜头视频素材" value={selectionKey(selected, "video")} onChange={e => chooseMedia("video", e.target.value)}><option value="">选择视频或已配置的视频卡</option>{choices.filter(choice => choice.kind === "video").map(choice => <option key={choice.key} value={choice.key} disabled={choice.missing}>{choice.title}</option>)}{selectionKey(selected, "video") && !choices.some(choice => choice.key === selectionKey(selected, "video")) && <option value={selectionKey(selected, "video")}>已固定的视频版本</option>}</StudioSelect></label>
            {selected.video_version_id && <div className="production-selected-media"><img src={mediaUrl(selected.video_version_id)} alt="已采用的视频"/><span>固定素材版本{versions[selected.video_version_id]?.duration ? ` · 原片 ${seconds(versions[selected.video_version_id].duration!)}` : ""}<small>源卡换用候选后，在这里明确采用更新。</small></span></div>}
            {(selected.latest_video_version_id && selected.latest_video_version_id !== selected.video_version_id || selected.video_node_id && choices.some(choice => choice.nodeId === selected.video_node_id && choice.versionId && choice.versionId !== selected.video_version_id)) && <button className="production-update-reference" onClick={() => { const latest = choices.find(choice => choice.nodeId === selected.video_node_id)?.versionId || selected.latest_video_version_id; if (latest) editShot(selected.id, { video_version_id: latest, status: "draft" }); }}><RefreshCw size={13}/>采用源卡当前视频</button>}
            <div className="production-fields two"><label><span>视频裁剪起点（秒）</span><input aria-label="视频裁剪起点" type="number" min={0} step={.1} value={selected.trim_start} onChange={e => editShot(selected.id, { trim_start: Number(e.target.value) })}/></label><label><span>原视频音量</span><input aria-label="原视频音量" type="number" min={0} max={2} step={.1} value={selected.video_volume} onChange={e => editShot(selected.id, { video_volume: Number(e.target.value) })}/></label></div>
            {generationStatus(selected, "video")}
            {selected.video_node_id && <div className="production-source-actions"><button className="production-regenerate" onClick={() => void generate(selected, "video")}><Sparkles size={13}/>按源卡设置重做视频</button>{onLocate && <button onClick={() => onLocate(selected.video_node_id!)}><MapPin size={13}/>打开视频卡</button>}</div>}
          </section>
          <section className="production-media-section"><header><Music2 size={16}/><strong>对白与声音</strong></header>
            <label><span>说话人物 / 旁白</span><input aria-label="说话人物" placeholder="旁白" value={selected.speaker} onChange={e => editShot(selected.id, { speaker: e.target.value })}/></label>
            <label><span>台词与字幕</span><textarea aria-label="镜头台词" rows={3} placeholder="填入该镜头的准确台词，导出时作为字幕。" value={selected.dialogue} onChange={e => editShot(selected.id, { dialogue: e.target.value })}/></label>
            <label><span>采用配音 / 生成卡</span><StudioSelect aria-label="镜头配音素材" value={selectionKey(selected, "audio")} onChange={e => chooseMedia("audio", e.target.value)}><option value="">不添加独立配音</option>{choices.filter(choice => choice.kind === "audio").map(choice => <option key={choice.key} value={choice.key} disabled={choice.missing}>{choice.title}</option>)}{selectionKey(selected, "audio") && !choices.some(choice => choice.key === selectionKey(selected, "audio")) && <option value={selectionKey(selected, "audio")}>已固定的配音版本</option>}</StudioSelect></label>
            {selected.audio_version_id && <div className="production-audio-preview"><audio controls preload="metadata" src={mediaUrl(selected.audio_version_id, "original")}/><small>{versions[selected.audio_version_id]?.duration ? `配音 ${seconds(versions[selected.audio_version_id].duration!)}` : "固定音频版本"}</small></div>}
            {(selected.latest_audio_version_id && selected.latest_audio_version_id !== selected.audio_version_id || selected.audio_node_id && choices.some(choice => choice.nodeId === selected.audio_node_id && choice.versionId && choice.versionId !== selected.audio_version_id)) && <button className="production-update-reference" onClick={() => { const latest = choices.find(choice => choice.nodeId === selected.audio_node_id)?.versionId || selected.latest_audio_version_id; if (latest) editShot(selected.id, { audio_version_id: latest, status: "draft" }); }}><RefreshCw size={13}/>采用源卡当前配音</button>}
            <div className="production-fields two"><label><span>配音延迟（秒）</span><input aria-label="配音延迟" type="number" min={0} step={.1} value={selected.audio_offset} onChange={e => editShot(selected.id, { audio_offset: Number(e.target.value) })}/></label><label><span>配音音量</span><input aria-label="配音音量" type="number" min={0} max={2} step={.1} value={selected.audio_volume} onChange={e => editShot(selected.id, { audio_volume: Number(e.target.value) })}/></label></div>
            <div className="production-fields two"><label><span>字幕开始（镜头内秒）</span><input aria-label="字幕开始" type="number" min={0} step={.1} placeholder={String(subtitleWindow(selected).start)} value={selected.subtitle_start ?? ""} onChange={e => editShot(selected.id, { subtitle_start: e.target.value === "" ? null : Number(e.target.value) })}/></label><label><span>字幕结束（镜头内秒）</span><input aria-label="字幕结束" type="number" min={0} step={.1} placeholder={String(subtitleWindow(selected, selected.audio_version_id ? versions[selected.audio_version_id]?.duration || undefined : undefined).end)} value={selected.subtitle_end ?? ""} onChange={e => editShot(selected.id, { subtitle_end: e.target.value === "" ? null : Number(e.target.value) })}/></label></div>
            {generationStatus(selected, "audio")}
            {selected.audio_node_id && <div className="production-source-actions"><button className="production-regenerate" onClick={() => void generate(selected, "audio")}><Sparkles size={13}/>按镜头台词重做配音</button>{onLocate && <button onClick={() => onLocate(selected.audio_node_id!)}><MapPin size={13}/>打开配音卡</button>}</div>}
          </section>
          <label><span>连续性与返工备注</span><textarea aria-label="镜头返工备注" rows={2} placeholder="检查人物外貌、服装、动作衔接和台词。" value={selected.notes} onChange={e => editShot(selected.id, { notes: e.target.value })}/></label>
        </fieldset> : <div className="production-editor-empty"><Clapperboard size={42}/><h3>从镜头到成片</h3><p>按顺序安排镜头，采用画布上的视频与配音，检查后导出带字幕的成片。</p></div>}
      </main>
    </div>}
    {issues && <div className={`production-validation ${issues.length ? "has-issues" : "passed"}`} role="status">{issues.length ? <><strong>需要处理 {issues.length} 项</strong><ul>{issues.map((issue, index) => <li key={index}><button onClick={() => { if (issue.shotId) setSelectedId(issue.shotId); setPreviewShots(null); setShowOutput(false); }}>{issue.message}</button></li>)}</ul></> : <><CheckCircle2 size={16}/>已通过素材与时长检查，导出时还会核对原件。</>}</div>}
    {batch && !!batch.errors?.length && <div className="production-banner production-error"><span>部分镜头未提交：{batch.errors.map(message).join("；")}</span></div>}
    <div className="production-settings"><button className="production-settings-toggle" onClick={() => setSettingsOpen(!settingsOpen)}><span>成片设置</span><small>{settings.width} × {settings.height} · {settings.fps} fps{settings.background_audio_version_id ? " · 已添加配乐" : ""}</small><span>{settingsOpen ? "收起" : "展开"}</span></button>{settingsOpen && <fieldset disabled={!!busy} className="production-settings-fields"><label><span>画幅</span><StudioSelect aria-label="成片画幅" value={`${settings.width}x${settings.height}`} onChange={e => { const [width, height] = e.target.value.split("x").map(Number); editSettings({ width, height }); }}>{["1280x720", "720x1280", "1920x1080", "1080x1920", "864x480", "480x864", "720x720"].map(value => <option key={value} value={value}>{value.replace("x", " × ")}</option>)}{!["1280x720", "720x1280", "1920x1080", "1080x1920", "864x480", "480x864", "720x720"].includes(`${settings.width}x${settings.height}`) && <option value={`${settings.width}x${settings.height}`}>{settings.width} × {settings.height}</option>}</StudioSelect></label><label><span>帧率</span><StudioSelect aria-label="成片帧率" value={settings.fps} onChange={e => editSettings({ fps: Number(e.target.value) })}>{[24, 25, 30, 60].map(value => <option key={value} value={value}>{value} fps</option>)}</StudioSelect></label><label className="production-music-select"><span>背景音乐</span><StudioSelect aria-label="背景音乐" value={settings.background_audio_version_id || ""} onChange={e => editSettings({ background_audio_version_id: e.target.value || null })}><option value="">无配乐</option>{choices.filter(choice => choice.kind === "audio" && choice.versionId).filter((choice, index, all) => all.findIndex(item => item.versionId === choice.versionId) === index).map(choice => <option key={choice.versionId} value={choice.versionId}>{choice.title}</option>)}</StudioSelect></label><label><span>配乐音量</span><input type="number" aria-label="配乐音量" min={0} max={2} step={.05} value={settings.background_volume} onChange={e => editSettings({ background_volume: Number(e.target.value) })}/></label></fieldset>}</div>
    {render && <div className={`production-render-status ${render.status}`}><span>{activeRender(render) ? <LoaderCircle size={16} className="spin"/> : render.status === "succeeded" ? <CheckCircle2 size={16}/> : <Film size={16}/>}<strong>{{pending:"等待导出",running:"正在合成",succeeded:"成片已入库",failed:"导出失败"}[render.status]}</strong><small>{render.message || (render.error ? message(render.error) : "")}</small></span>{activeRender(render) && <progress max={1} value={render.progress || 0}/>}<div>{render.output_version_id && <><button onClick={() => { setShowOutput(true); setPreviewShots(null); setSettingsOpen(false); setIssues(null); }}><Play size={14}/>播放成片</button><a href={mediaUrl(render.output_version_id, "original", true)} download><Download size={14}/>下载</a></>}{render.status === "failed" && <button disabled={!!busy} onClick={() => void action("retry", async () => { setRender(await api<ProductionRender>(`/api/production/renders/${render.id}/retry`, { method: "POST", body: JSON.stringify({ request_id: crypto.randomUUID() }) })); })}><RefreshCw size={14}/>重试</button>}</div></div>}
    <footer className="production-footer"><div><button disabled={!!busy || loading} onClick={() => void action("save", async () => { await save(); setNotice("分镜已保存。"); })} className="button secondary">{busy === "save" ? <LoaderCircle className="spin" size={15}/> : <Save size={15}/>}保存</button><button disabled={!!busy || !shots.length} onClick={() => { const found = validate(); setIssues(found); }}><Check size={15}/>检查</button><button disabled={!!busy || !shots.length} onClick={() => preview(shots)}><Play size={15}/>连播</button><button disabled={!!busy || !shots.length} onClick={() => void generate()}><Sparkles size={15}/>生成缺失素材</button></div><div><button disabled={!!busy || !shots.length} onClick={() => void downloadHandoff("subtitles")} title="导出 SRT 字幕">SRT</button><button disabled={!!busy || !shots.length} onClick={() => void downloadHandoff("handoff")} title="导出视频、配音、字幕和镜头清单"><FolderDown size={15}/>剪辑包</button><button className="button primary" disabled={!!busy || loading || !shots.length || activeRender(render)} onClick={() => void startRender()}>{busy === "render" || activeRender(render) ? <LoaderCircle className="spin" size={15}/> : <Film size={15}/>}导出成片</button></div></footer>
  </Modal>;
}
