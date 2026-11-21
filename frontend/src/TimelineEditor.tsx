import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { ArrowDown, ArrowUp, Check, Download, Film, GripVertical, Layers3, LoaderCircle, LockKeyhole, Music2, Pause, Play, Plus, Redo2, RefreshCw, Save, Scissors, Search, Trash2, Type, Undo2, UnlockKeyhole, Volume2, VolumeX, X } from "lucide-react";
import { api, mediaUrl } from "./api";
import { Modal } from "./ui";
import StudioSelect from "./StudioSelect";
import type { Asset, AssetPage, AssetVersion } from "./types";
import type { ProductionRender } from "./productionTypes";
import TimelinePreview from "./TimelinePreview";
import { defaultTimelineSettings, timelineDuration, timelineTime, type TimelineClip, type TimelineDocument, type TimelineDraft, type TimelineEdit, type TimelineTrack, type TimelineTrackKind } from "./timelineTypes";

type Props = { projectId: string; onClose: () => void; onChanged: () => void };
type Drag = { id: string; mode: "move" | "left" | "right"; x: number; clip: TimelineClip; trackType: TimelineTrackKind; snapshot: TimelineEdit };
const empty: TimelineEdit = { settings: defaultTimelineSettings, tracks: [], clips: [] };
const errorText = (error: unknown) => error instanceof Error ? error.message : typeof error === "string" ? error : JSON.stringify(error);
const running = (render?: ProductionRender) => !!render && ["pending", "running"].includes(render.status);
const trackNames: Record<TimelineTrackKind, string> = { video: "画面", audio: "音频", text: "文字" };
const trackIcon = (kind: TimelineTrackKind, size = 14) => kind === "audio" ? <Music2 size={size}/> : kind === "text" ? <Type size={size}/> : <Film size={size}/>;
const draftKey = (id: string) => `manju:timeline-draft:${id}`;
const round = (value: number) => Math.round(value * 1000000) / 1000000;

function downloadDraft(value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "多轨剪辑草稿.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function TimelineEditor({ projectId, onClose, onChanged, page = false }: Props & { page?: boolean }) {
  const [server, setServer] = useState<TimelineDocument>(), [edit, setEdit] = useState<TimelineEdit>(empty);
  const [assets, setAssets] = useState<Asset[]>([]), [versions, setVersions] = useState<Record<string, AssetVersion>>({});
  const [loading, setLoading] = useState(true), [dirty, setDirty] = useState(false), [busy, setBusy] = useState("");
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [draft, setDraft] = useState<TimelineDraft>();
  const [selected, setSelected] = useState(""), [selectedTrack, setSelectedTrack] = useState("");
  const [time, setTime] = useState(0), [playing, setPlaying] = useState(false), [zoom, setZoom] = useState(36), [snap, setSnap] = useState(true);
  const [search, setSearch] = useState(""), [assetType, setAssetType] = useState(""), [settingsOpen, setSettingsOpen] = useState(false);
  const [render, setRender] = useState<ProductionRender>(), [showOutput, setShowOutput] = useState(false), [historyTick, setHistoryTick] = useState(0);
  const alive = useRef(true), current = useRef({ edit, server, dirty, busy }); current.current = { edit, server, dirty, busy };
  const undo = useRef<TimelineEdit[]>([]), redo = useRef<TimelineEdit[]>([]), dragging = useRef<Drag | null>(null);
  const request = useRef<{ fingerprint: string; id: string } | null>(null), renderRequest = useRef<{ revision: number; id: string } | null>(null), importRequest = useRef<{ revision: number; id: string } | null>(null);
  const onChangedRef = useRef(onChanged); onChangedRef.current = onChanged;
  const base = `/api/projects/${encodeURIComponent(projectId)}/timeline`;
  const duration = timelineDuration(edit), sortedTracks = useMemo(() => [...edit.tracks].sort((a, b) => b.order - a.order), [edit.tracks]);
  const chosen = edit.clips.find(clip => clip.id === selected), chosenTrack = edit.tracks.find(track => track.id === (chosen?.track_id || selectedTrack));
  const editable = !!chosen && !chosen.locked && !chosenTrack?.locked && !busy;
  const frame = 1 / edit.settings.fps;
  const rulerDuration = Math.max(20, Math.ceil((Math.max(duration, time) + 4) / 10) * 10), rulerWidth = rulerDuration * zoom;
  const rulerStep = zoom < 20 ? 5 : zoom < 45 ? 2 : 1;

  const loadMedia = useCallback(async () => {
    const first = await api<AssetPage>(`/api/assets?project_id=${encodeURIComponent(projectId)}&limit=500`), items = [...first.items];
    for (let offset = 500; offset < first.total; offset += 500) items.push(...(await api<AssetPage>(`/api/assets?project_id=${encodeURIComponent(projectId)}&limit=500&offset=${offset}`)).items);
    if (!alive.current) return;
    setAssets(items); setVersions(previous => ({ ...previous, ...Object.fromEntries(items.map(asset => [asset.version.id, asset.version])) }));
  }, [projectId]);
  const accept = useCallback((value: TimelineDocument) => {
    const next = { settings: value.settings, tracks: value.tracks, clips: value.clips };
    setServer(value); setEdit(next); setDirty(false); current.current = { ...current.current, edit: next, server: value, dirty: false };
    setRender(value.renders?.find(item => running(item)) || value.renders?.[0]);
    setSelected(id => value.clips.some(clip => clip.id === id) ? id : "");
    setSelectedTrack(id => value.tracks.some(track => track.id === id) ? id : value.tracks[0]?.id || "");
  }, []);
  const load = useCallback(async () => { const value = await api<TimelineDocument>(base); if (alive.current) accept(value); }, [base, accept]);
  useEffect(() => {
    alive.current = true;
    try { const stored = JSON.parse(localStorage.getItem(draftKey(projectId)) || "null"); if (stored?.clips && stored?.tracks && stored?.settings) setDraft(stored); } catch { /* Ignore incomplete browser drafts. */ }
    void Promise.all([load(), loadMedia()]).catch(value => { if (alive.current) setError(errorText(value)); }).finally(() => { if (alive.current) setLoading(false); });
    return () => { alive.current = false; };
  }, [projectId, load, loadMedia]);
  useEffect(() => {
    if (!dirty || !server) return;
    try { localStorage.setItem(draftKey(projectId), JSON.stringify({ ...edit, revision: server.revision, saved_at: Date.now() })); }
    catch { setNotice("浏览器存储已满，请保存剪辑或下载草稿。"); }
  }, [edit, dirty, server, projectId]);
  useEffect(() => {
    const ids = [...new Set(edit.clips.map(clip => clip.asset_version_id).filter((id): id is string => !!id))].filter(id => !versions[id]);
    if (!ids.length) return;
    let disposed = false;
    void Promise.allSettled(ids.map(async id => [id, (await api<{ version: AssetVersion }>(`/api/versions/${id}`)).version] as const)).then(results => {
      if (disposed || !alive.current) return;
      const found: Record<string, AssetVersion> = {};
      results.forEach((item, index) => { found[ids[index]] = item.status === "fulfilled" ? item.value[1] : { id: ids[index], missing: true } as AssetVersion; });
      setVersions(previous => ({ ...previous, ...found }));
    });
    return () => { disposed = true; };
  }, [edit.clips, versions]);
  useEffect(() => {
    if (!render || !running(render)) return;
    let disposed = false, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<ProductionRender>(`/api/production/renders/${render.id}`);
        if (disposed || !alive.current) return;
        setRender(next);
        if (next.status === "succeeded") {
          setNotice("多轨成片已保存到项目画布和资产库。"); onChangedRef.current(); await loadMedia();
          const value = await api<TimelineDocument>(base);
          if (!disposed && alive.current && !current.current.dirty) accept(value);
        }
      } catch (value) { if (!disposed) setNotice(`导出状态暂时无法读取，后台任务会继续：${errorText(value)}`); }
      if (!disposed) timer = setTimeout(() => void poll(), 1500);
    };
    timer = setTimeout(() => void poll(), 500);
    return () => { disposed = true; clearTimeout(timer); };
  }, [render?.id, render?.status, base, loadMedia, accept]);

  function change(next: TimelineEdit, remember = true) {
    if (remember) { undo.current = [...undo.current.slice(-49), current.current.edit]; redo.current = []; setHistoryTick(value => value + 1); }
    current.current = { ...current.current, edit: next, dirty: true }; setEdit(next); setDirty(true); setError(""); setPlaying(false); setShowOutput(false);
  }
  function travel(back: boolean) {
    const source = back ? undo : redo, destination = back ? redo : undo, next = source.current.pop();
    if (!next) return;
    destination.current.push(current.current.edit); change(next, false); setHistoryTick(value => value + 1);
  }
  function editClip(patch: Partial<TimelineClip>) {
    if (!chosen || chosenTrack?.locked || busy || chosen.locked && patch.locked !== false) return;
    const next = { ...chosen, ...patch }; delete next.trim_end;
    change({ ...edit, clips: edit.clips.map(clip => clip.id === chosen.id ? next : clip) });
  }
  function chooseVersion(id: string, keepSource = false) {
    if (!chosen || !id) return;
    const source = versions[id], duration = source?.duration ? Math.max(frame, Math.min(chosen.duration, Math.floor(source.duration / frame) * frame)) : chosen.duration;
    editClip({ asset_version_id: id, ...(keepSource ? {} : { source_node_id: null }), trim_start: 0, duration, fade_in: Math.min(chosen.fade_in, duration), fade_out: Math.min(chosen.fade_out, duration), stale: false });
  }
  function patchTrack(id: string, patch: Partial<TimelineTrack>) { change({ ...edit, tracks: edit.tracks.map(track => track.id === id ? { ...track, ...patch } : track) }); }
  function makeTrack(kind: TimelineTrackKind): TimelineTrack { return { id: crypto.randomUUID(), name: `${trackNames[kind]} ${edit.tracks.filter(track => track.type === kind).length + 1}`, type: kind, order: Math.max(0, ...edit.tracks.map(track => track.order)) + 1, muted: false, locked: false }; }
  function addTrack(kind: TimelineTrackKind) { const track = makeTrack(kind); change({ ...edit, tracks: [...edit.tracks, track] }); setSelectedTrack(track.id); setSelected(""); }
  function addClip(asset?: Asset, trackId?: string, at = time) {
    const kind: TimelineTrackKind = !asset ? "text" : asset.type === "audio" ? "audio" : "video";
    let target = edit.tracks.find(track => track.id === (trackId || selectedTrack) && track.type === kind && !track.locked);
    if (trackId && !target) { setNotice("这个轨道已锁定或不接受该素材类型。"); return; }
    let tracks = edit.tracks;
    if (!target) { target = edit.tracks.find(track => track.type === kind && !track.locked); if (!target) { target = makeTrack(kind); tracks = [...tracks, target]; } }
    const clip: TimelineClip = { id: crypto.randomUUID(), track_id: target.id, start: round(Math.max(0, Math.round(at / frame) * frame)), duration: round(asset?.type === "image" || !asset ? 5 : Math.max(frame, Math.floor(Math.min(30, asset.version.duration || 5) / frame) * frame)), trim_start: 0, asset_version_id: asset?.current_version_id || null, text: asset ? "" : "输入字幕或标题", transform: { x: kind === "text" ? 40 : 0, y: kind === "text" ? edit.settings.height - 100 : 0, scale: 1, opacity: 1 }, volume: 1, fade_in: 0, fade_out: 0, text_style: { font_size: 42, color: "#ffffff", background_color: "transparent", align: "center" } };
    change({ ...edit, tracks, clips: [...edit.clips, clip] }); setSelected(clip.id); setSelectedTrack(target.id); setNotice("");
  }
  function reorderTrack(id: string, direction: number) {
    const index = sortedTracks.findIndex(track => track.id === id), other = index + direction;
    if (other < 0 || other >= sortedTracks.length || sortedTracks[index].locked || sortedTracks[other].locked) return;
    const orders = new Map([[id, sortedTracks[other].order], [sortedTracks[other].id, sortedTracks[index].order]]);
    change({ ...edit, tracks: edit.tracks.map(track => orders.has(track.id) ? { ...track, order: orders.get(track.id)! } : track) });
  }
  function split() {
    if (!chosen || !editable) return;
    const local = round(Math.round((time - chosen.start) / frame) * frame);
    if (local < frame - 1e-6 || chosen.duration - local < frame - 1e-6) { setNotice("把播放头放在片段内部再分割，左右至少保留一帧。"); return; }
    const left = { ...chosen, duration: local, fade_out: 0, fade_in: Math.min(chosen.fade_in, local) }, right = { ...chosen, id: crypto.randomUUID(), start: round(chosen.start + local), trim_start: chosen.asset_version_id ? round(chosen.trim_start + local) : 0, duration: round(chosen.duration - local), fade_in: 0, fade_out: Math.min(chosen.fade_out, chosen.duration - local) };
    delete left.trim_end; delete right.trim_end;
    change({ ...edit, clips: edit.clips.flatMap(clip => clip.id === chosen.id ? [left, right] : [clip]) }); setSelected(right.id);
  }
  const snapTime = (value: number, excluded: string, snapshot: TimelineEdit) => {
    let next = Math.max(0, Math.round(value * snapshot.settings.fps) / snapshot.settings.fps);
    if (snap) { const points = [0, time, ...snapshot.clips.filter(clip => clip.id !== excluded).flatMap(clip => [clip.start, clip.start + clip.duration])]; const near = points.filter(point => Math.abs(point - value) * zoom <= 7).sort((a, b) => Math.abs(a - value) - Math.abs(b - value))[0]; if (near !== undefined) next = near; }
    return round(next);
  };
  function beginDrag(event: ReactPointerEvent, clip: TimelineClip, mode: Drag["mode"]) {
    event.preventDefault(); event.stopPropagation(); setSelected(clip.id); setSelectedTrack(clip.track_id); setPlaying(false);
    const track = edit.tracks.find(item => item.id === clip.track_id);
    if (!track || track.locked || clip.locked || busy) return;
    dragging.current = { id: clip.id, mode, x: event.clientX, clip, trackType: track.type, snapshot: edit };
    undo.current = [...undo.current.slice(-49), edit]; redo.current = []; setHistoryTick(value => value + 1);
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function dragMove(event: ReactPointerEvent) {
    const drag = dragging.current;
    if (!drag) return;
    const delta = (event.clientX - drag.x) / zoom, original = drag.clip, next = { ...original };
    const source = original.asset_version_id ? versions[original.asset_version_id] : undefined;
    const sourceDuration = source?.mime?.startsWith("image/") || drag.trackType === "text" ? undefined : source?.duration || undefined;
    if (drag.mode === "move") {
      next.start = snapTime(original.start + delta, original.id, drag.snapshot);
      const lane = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>("[data-timeline-track]");
      const track = drag.snapshot.tracks.find(item => item.id === lane?.dataset.timelineTrack);
      if (track?.type === drag.trackType && !track.locked) next.track_id = track.id;
    } else if (drag.mode === "left") {
      const minimum = Math.max(0, original.start - (sourceDuration ? original.trim_start : original.start));
      next.start = Math.min(original.start + original.duration - frame, Math.max(minimum, snapTime(original.start + delta, original.id, drag.snapshot)));
      const movement = next.start - original.start; next.duration = round(original.duration - movement);
      next.trim_start = sourceDuration ? round(original.trim_start + movement) : original.trim_start;
    } else {
      const end = snapTime(original.start + original.duration + delta, original.id, drag.snapshot);
      next.duration = round(Math.max(frame, Math.min(end - original.start, sourceDuration ? Math.floor((sourceDuration - original.trim_start + 1e-6) / frame) * frame : 3600)));
    }
    next.fade_in = Math.min(next.fade_in, next.duration); next.fade_out = Math.min(next.fade_out, next.duration); delete next.trim_end;
    change({ ...drag.snapshot, clips: drag.snapshot.clips.map(clip => clip.id === drag.id ? next : clip) }, false);
  }
  function endDrag() { dragging.current = null; }
  function seek(value: number) { setPlaying(false); setTime(round(Math.max(0, Math.min(rulerDuration, Math.round(value / frame) * frame)))); }

  async function save(): Promise<TimelineDocument> {
    const value = current.current;
    if (!value.server) throw new Error("时间线尚未读取完成。");
    if (!value.dirty) return value.server;
    const fingerprint = JSON.stringify({ revision: value.server.revision, ...value.edit });
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, id: crypto.randomUUID() };
    const result = await api<TimelineDocument>(base, { method: "PUT", body: JSON.stringify({ revision: value.server.revision, ...value.edit, request_id: request.current.id }) });
    request.current = null;
    if (alive.current) { accept(result); localStorage.removeItem(draftKey(projectId)); setDraft(undefined); onChangedRef.current(); }
    return result;
  }
  async function action(name: string, callback: () => Promise<void>) {
    if (current.current.busy) return;
    setBusy(name); current.current.busy = name; setError(""); setNotice(""); setPlaying(false);
    try { await callback(); } catch (value) { if (alive.current) setError(errorText(value)); }
    finally { if (alive.current) { setBusy(""); current.current.busy = ""; } }
  }
  function validation() {
    const messages: string[] = [];
    if (!edit.clips.length) messages.push("请添加素材或从分镜导入。");
    for (const clip of edit.clips) {
      const track = edit.tracks.find(item => item.id === clip.track_id); if (track?.muted || clip.muted) continue;
      const source = clip.asset_version_id ? versions[clip.asset_version_id] : undefined;
      if (track?.type !== "text" && (!clip.asset_version_id || source?.missing)) messages.push(`${track?.name || "片段"}：素材原件缺失。`);
      if (!Number.isFinite(clip.duration) || clip.duration < frame - 1e-6) messages.push("每个片段至少需要一帧。");
      if (source?.duration && clip.trim_start + clip.duration > source.duration + frame) messages.push(`${source.filename}：裁剪范围超出素材时长。`);
      if (clip.start < 0 || clip.trim_start < 0) messages.push("片段起点和入点不能为负数。");
      if (track?.type === "text" && !clip.text.trim()) messages.push("文字片段内容不能为空。");
    }
    return [...new Set(messages)];
  }
  async function startRender() {
    const messages = validation(); if (messages.length) { setError(messages.join("；")); return; }
    await action("render", async () => {
      const saved = await save();
      if (renderRequest.current?.revision !== saved.revision) renderRequest.current = { revision: saved.revision, id: crypto.randomUUID() };
      const result = await api<ProductionRender>(`${base}/render`, { method: "POST", body: JSON.stringify({ revision: saved.revision, request_id: renderRequest.current.id }) });
      renderRequest.current = null; setRender(result); setNotice("多轨成片正在导出，可以关闭窗口，任务会继续。");
    });
  }
  async function importProduction() {
    await action("import", async () => {
      const saved = await save();
      if (importRequest.current?.revision !== saved.revision) importRequest.current = { revision: saved.revision, id: crypto.randomUUID() };
      const result = await api<TimelineDocument>(`${base}/import-production`, { method: "POST", body: JSON.stringify({ revision: saved.revision, request_id: importRequest.current.id }) });
      importRequest.current = null; accept(result); undo.current = []; redo.current = []; setHistoryTick(value => value + 1); await loadMedia(); onChangedRef.current(); setNotice("分镜画面、配音和字幕已追加为独立轨道，原有剪辑已保留。");
    });
  }
  function restoreDraft() {
    if (!draft) return;
    try { localStorage.setItem(`${draftKey(projectId)}:backup:${draft.saved_at}`, JSON.stringify(draft)); }
    catch { setError("无法备份草稿，请先下载草稿。"); return; }
    const mapping = new Map(draft.tracks.map(track => [track.id, crypto.randomUUID()])), highest = Math.max(0, ...edit.tracks.map(track => track.order));
    change({ ...edit, tracks: [...edit.tracks, ...draft.tracks.map((track, index) => ({ ...track, id: mapping.get(track.id)!, name: `${track.name}（恢复副本）`, locked: false, order: highest + index + 1 }))], clips: [...edit.clips, ...draft.clips.map(clip => ({ ...clip, id: crypto.randomUUID(), track_id: mapping.get(clip.track_id)!, locked: false }))] });
    setDraft(undefined); setNotice("已追加草稿轨道副本，保留当前剪辑、设置和原始备份。");
  }
  const visibleAssets = assets.filter(asset => (!assetType || asset.type === assetType) && (!search || asset.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())));
  const clipLabel = (clip: TimelineClip) => clip.name || (edit.tracks.find(track => track.id === clip.track_id)?.type === "text" ? clip.text || "文字" : assets.find(asset => asset.current_version_id === clip.asset_version_id)?.name || (clip.asset_version_id ? versions[clip.asset_version_id]?.filename : "未选择素材") || "素材");
  const numeric = (label: string, value: number, update: (value: number) => void, min = 0, max?: number, step = .1) => <label><span>{label}</span><input aria-label={label} type="number" min={min} max={max} step={step} value={Number(value.toFixed(5))} onChange={event => { const n = Number(event.target.value); if (Number.isFinite(n)) update(Math.max(min, max === undefined ? n : Math.min(max, n))); }}/></label>;

  return <Modal title="多轨剪辑" className="timeline-modal" onClose={onClose} wide page={page} backLabel="返回画布">
    <div className="timeline-toolbar"><div><span className="timeline-document-state">{dirty ? "草稿已保留在本机" : "已保存"}</span><button disabled={loading || !!busy} onClick={() => void action("save", async () => { await save(); setNotice("多轨剪辑已保存。"); })}><Save size={15}/>保存</button><button disabled={!!busy || !undo.current.length} title="撤销" aria-label="撤销剪辑" onClick={() => travel(true)}><Undo2 size={15}/></button><button disabled={!!busy || !redo.current.length} title="重做" aria-label="重做剪辑" onClick={() => travel(false)}><Redo2 size={15}/></button><button disabled={loading || !!busy} onClick={() => void importProduction()}><Layers3 size={15}/>从分镜导入</button></div><div><button disabled={loading || !!busy} onClick={() => void action("refresh", async () => { await loadMedia(); if (!current.current.dirty) await load(); setNotice("素材已刷新，未保存剪辑已保留。"); })} aria-label="刷新剪辑素材"><RefreshCw size={15}/></button><button className={settingsOpen ? "active" : ""} onClick={() => setSettingsOpen(!settingsOpen)}>{edit.settings.width} × {edit.settings.height} · {edit.settings.fps} fps</button><button className="timeline-export" disabled={loading || !!busy || running(render) || !edit.clips.length} onClick={() => void startRender()}>{busy === "render" || running(render) ? <LoaderCircle size={15} className="spin"/> : <Film size={15}/>}导出成片</button></div></div>
    {error && <div className="timeline-banner error" role="alert"><span>{error}</span>{dirty && <><button onClick={() => downloadDraft({ ...edit, revision: server?.revision, saved_at: Date.now() })}>下载草稿</button><button disabled={!!busy} onClick={() => void action("reload", async () => { const backup = { ...current.current.edit, revision: current.current.server?.revision || 0, saved_at: Date.now() }; localStorage.setItem(draftKey(projectId), JSON.stringify(backup)); setDraft(backup); await load(); undo.current = []; redo.current = []; setHistoryTick(value => value + 1); setNotice("已读取最新剪辑；本机草稿可恢复为独立轨道副本。"); })}>保留草稿并加载最新</button></>}</div>}
    {notice && <div className="timeline-banner" role="status">{notice}</div>}
    {draft && <div className="timeline-banner"><span>发现本机草稿：{draft.tracks.length} 轨、{draft.clips.length} 个片段。恢复会追加轨道副本。</span><button disabled={!!busy || loading} onClick={restoreDraft}>恢复为轨道副本</button><button onClick={() => downloadDraft(draft)}>下载草稿</button><button onClick={() => { localStorage.removeItem(draftKey(projectId)); setDraft(undefined); }}>丢弃草稿</button></div>}
    {settingsOpen && <fieldset className="timeline-settings" disabled={!!busy}>{numeric("输出宽度", edit.settings.width, width => change({ ...edit, settings: { ...edit.settings, width: Math.round(width / 2) * 2 } }), 64, 3840, 2)}{numeric("输出高度", edit.settings.height, height => change({ ...edit, settings: { ...edit.settings, height: Math.round(height / 2) * 2 } }), 64, 3840, 2)}<label><span>帧率</span><StudioSelect aria-label="时间线帧率" value={edit.settings.fps} onChange={event => change({ ...edit, settings: { ...edit.settings, fps: Number(event.target.value) } })}>{[24, 25, 30, 50, 60].map(fps => <option key={fps} value={fps}>{fps} fps</option>)}</StudioSelect></label><label><span>背景颜色</span><input aria-label="时间线背景颜色" type="color" value={edit.settings.background_color.slice(0, 7)} onChange={event => change({ ...edit, settings: { ...edit.settings, background_color: event.target.value } })}/></label><label><span>成片时长（空白为自动）</span><input aria-label="固定成片时长" type="number" min={frame} step={frame} value={edit.settings.duration ?? ""} onChange={event => change({ ...edit, settings: { ...edit.settings, duration: event.target.value ? Math.max(frame, Number(event.target.value)) : null } })}/></label></fieldset>}
    {loading ? <div className="timeline-loading"><LoaderCircle className="spin"/>正在读取时间线…</div> : <>
      <div className="timeline-workbench">
        <aside className="timeline-assets"><header><strong>项目素材</strong><small>{assets.length}</small></header><label className="timeline-search"><Search size={13}/><input aria-label="搜索剪辑素材" placeholder="搜索素材" value={search} onChange={event => setSearch(event.target.value)}/></label><div className="timeline-asset-filters">{[["", "全部"], ["video", "视频"], ["audio", "音频"], ["image", "图片"]].map(([kind, label]) => <button key={kind} className={assetType === kind ? "active" : ""} onClick={() => setAssetType(kind)}>{label}</button>)}</div><div className="timeline-asset-list">{visibleAssets.map(asset => <article key={asset.id} className="timeline-asset" draggable={!asset.version.missing && !busy} onDragStart={event => event.dataTransfer.setData("application/x-manju-timeline-asset", asset.id)}><div className={`timeline-asset-thumb ${asset.type}`}>{asset.type === "audio" ? <Music2 size={23}/> : <img src={mediaUrl(asset.current_version_id)} alt="" loading="lazy"/>}<button disabled={!!busy || asset.version.missing} title={`添加 ${asset.name}`} aria-label={`添加素材 ${asset.name}`} onClick={() => addClip(asset)}><Plus size={14}/></button></div><strong title={asset.name}>{asset.name}</strong><small>{asset.version.missing ? "原件缺失" : asset.type === "image" ? "图片" : `${(asset.version.duration || 0).toFixed(1)} 秒`}</small></article>)}</div><p>拖入对应轨道，或点 + 添加到播放头。</p></aside>
        <section className="timeline-monitor">{showOutput && render?.output_version_id ? <div className="timeline-final-preview"><button aria-label="关闭多轨成片预览" onClick={() => setShowOutput(false)}><X size={15}/></button><video controls autoPlay playsInline src={mediaUrl(render.output_version_id, "original")}/></div> : <TimelinePreview edit={edit} versions={versions} time={time} playing={playing} onTime={setTime} onPlayingChange={setPlaying}/>}<div className="timeline-playback"><button aria-label={playing ? "暂停时间线" : "播放时间线"} disabled={!duration || showOutput} onClick={() => { if (time >= duration) setTime(0); setPlaying(!playing); }}>{playing ? <Pause size={18}/> : <Play size={18}/>}</button><input aria-label="播放头秒数" type="number" min={0} step={frame} value={Number(time.toFixed(3))} onChange={event => seek(Number(event.target.value))}/><span>/ {timelineTime(duration)}</span><button disabled={!editable} onClick={split}><Scissors size={14}/>分割</button><span className="timeline-preview-note">实时预览 · 导出采用精确帧与音频混合</span></div></section>
        <aside className="timeline-inspector"><header><strong>{chosen ? "片段属性" : chosenTrack ? "轨道属性" : "剪辑属性"}</strong>{chosen && <><button disabled={!!busy || chosenTrack?.locked} aria-label={chosen.locked ? "解锁片段" : "锁定片段"} onClick={() => editClip({ locked: !chosen.locked })}>{chosen.locked ? <LockKeyhole size={14}/> : <UnlockKeyhole size={14}/>}</button><button disabled={!editable} aria-label="删除选中片段" onClick={() => { change({ ...edit, clips: edit.clips.filter(clip => clip.id !== chosen.id) }); setSelected(""); }}><Trash2 size={14}/></button></>}</header>{chosen && chosenTrack ? <fieldset disabled={!editable}>
          <p className="timeline-selected-name">{clipLabel(chosen)}</p>{(chosenTrack.locked || chosen.locked) && <p className="timeline-locked-hint">已锁定，请先解锁再编辑。</p>}<label><span>片段名称</span><input aria-label="片段名称" value={chosen.name || ""} placeholder={clipLabel(chosen)} onChange={event => editClip({ name: event.target.value })}/></label><button aria-pressed={!!chosen.muted} onClick={() => editClip({ muted: !chosen.muted })}>{chosen.muted ? <VolumeX size={13}/> : <Volume2 size={13}/>} {chosen.muted ? "启用此片段" : "静音或隐藏此片段"}</button>
          <div className="timeline-fields two">{numeric("开始时间", chosen.start, start => editClip({ start }), 0, undefined, frame)}{numeric("片段时长", chosen.duration, value => editClip({ duration: value, fade_in: Math.min(chosen.fade_in, value), fade_out: Math.min(chosen.fade_out, value) }), frame, 3600, frame)}</div>
          {chosenTrack.type !== "text" && <><label><span>采用素材版本</span><StudioSelect aria-label="片段素材版本" value={chosen.asset_version_id || ""} onChange={event => chooseVersion(event.target.value)}><option value="">选择项目素材</option>{assets.filter(asset => chosenTrack.type === "audio" ? asset.type === "audio" || asset.type === "video" : asset.type !== "audio").map(asset => <option key={asset.id} value={asset.current_version_id} disabled={asset.version.missing}>{asset.name}</option>)}{chosen.asset_version_id && !assets.some(asset => asset.current_version_id === chosen.asset_version_id) && <option value={chosen.asset_version_id}>已固定的素材版本</option>}</StudioSelect></label>{chosen.stale && chosen.latest_version_id && <button onClick={() => chooseVersion(chosen.latest_version_id!, true)}><RefreshCw size={12}/>源卡已更新 · 采用最新版本</button>}{numeric("素材入点", chosen.trim_start, trim_start => editClip({ trim_start }), 0, undefined, frame)}</>}
          {chosenTrack.type === "text" && <><label><span>文字内容</span><textarea aria-label="文字片段内容" rows={3} value={chosen.text} onChange={event => editClip({ text: event.target.value })}/></label><div className="timeline-fields two">{numeric("字号", chosen.text_style.font_size, font_size => editClip({ text_style: { ...chosen.text_style, font_size } }), 8, 300, 1)}<label><span>文字颜色</span><input aria-label="文字颜色" type="color" value={chosen.text_style.color.slice(0, 7)} onChange={event => editClip({ text_style: { ...chosen.text_style, color: event.target.value } })}/></label></div><label><span>文字对齐</span><StudioSelect aria-label="文字对齐" value={chosen.text_style.align} onChange={event => editClip({ text_style: { ...chosen.text_style, align: event.target.value as "left" | "center" | "right" } })}><option value="left">左对齐</option><option value="center">居中</option><option value="right">右对齐</option></StudioSelect></label><label><span>文字底色</span><input aria-label="文字底色" placeholder="transparent 或 #00000080" value={chosen.text_style.background_color} onChange={event => editClip({ text_style: { ...chosen.text_style, background_color: event.target.value } })}/></label></>}
          {chosenTrack.type !== "audio" && <><div className="timeline-inspector-divider">画面布局</div><div className="timeline-fields two">{numeric("位置 X", chosen.transform.x, x => editClip({ transform: { ...chosen.transform, x } }), -edit.settings.width * 2, edit.settings.width * 2, 1)}{numeric("位置 Y", chosen.transform.y, y => editClip({ transform: { ...chosen.transform, y } }), -edit.settings.height * 2, edit.settings.height * 2, 1)}{numeric("缩放", chosen.transform.scale, scale => editClip({ transform: { ...chosen.transform, scale } }), .02, 8, .05)}{numeric("不透明度", chosen.transform.opacity, opacity => editClip({ transform: { ...chosen.transform, opacity } }), 0, 1, .05)}</div></>}
          <div className="timeline-inspector-divider">声音与渐变</div>{chosenTrack.type !== "text" && <><label><span>声音处理</span><StudioSelect aria-label="片段声音处理" value={chosen.audio_preset || "none"} onChange={event => editClip({ audio_preset: event.target.value as TimelineClip["audio_preset"] })}><option value="none">原始声音</option><option value="dialogue">影视对白</option><option value="phone">电话声音</option><option value="narration">旁白</option></StudioSelect></label>{numeric("片段音量", chosen.volume, volume => editClip({ volume }), 0, 4, .05)}</>}<div className="timeline-fields two">{numeric("淡入秒数", chosen.fade_in, fade_in => editClip({ fade_in }), 0, chosen.duration, .1)}{numeric("淡出秒数", chosen.fade_out, fade_out => editClip({ fade_out }), 0, chosen.duration, .1)}</div>
          {chosen.asset_version_id && <a className="timeline-source-link" href={mediaUrl(chosen.asset_version_id, "original", true)} download><Download size={13}/>下载已采用的原始素材</a>}
        </fieldset> : chosenTrack ? <fieldset disabled={!!busy || chosenTrack.locked}><label><span>轨道名称</span><input aria-label="轨道名称" value={chosenTrack.name} onChange={event => patchTrack(chosenTrack.id, { name: event.target.value })}/></label><p>{trackNames[chosenTrack.type]}轨 · {edit.clips.filter(clip => clip.track_id === chosenTrack.id).length} 个片段</p><p>上方轨道覆盖下方轨道。同轨重叠时，后添加的片段显示在前。</p><button className="timeline-remove-track" onClick={() => { change({ ...edit, tracks: edit.tracks.filter(track => track.id !== chosenTrack.id), clips: edit.clips.filter(clip => clip.track_id !== chosenTrack.id) }); setSelectedTrack(""); }}><Trash2 size={14}/>删除轨道与片段</button></fieldset> : <div className="timeline-empty-inspector"><Layers3 size={28}/><p>选择片段以调整时间、画面和声音。</p><button disabled={!!busy} onClick={() => addClip()}><Type size={14}/>添加文字</button></div>}</aside>
      </div>
      <div className="timeline-edit-toolbar"><div>{(["video", "audio", "text"] as const).map(kind => <button disabled={!!busy} key={kind} onClick={() => addTrack(kind)}><Plus size={13}/>{trackIcon(kind)}{trackNames[kind]}轨</button>)}<button disabled={!!busy} onClick={() => addClip()}><Type size={14}/>文字片段</button></div><div><button className={snap ? "active" : ""} aria-pressed={snap} onClick={() => setSnap(!snap)}><Check size={13}/>吸附</button><label>缩放<input aria-label="时间线缩放" type="range" min={12} max={110} step={2} value={zoom} onChange={event => setZoom(Number(event.target.value))}/></label><span>{edit.tracks.length} 轨 · {edit.clips.length} 片段</span></div></div>
      <div className="timeline-scroll" data-history={historyTick}>
        <div className="timeline-grid" style={{ minWidth: rulerWidth + 172 }}><div className="timeline-ruler-row"><div className="timeline-track-heading">上层覆盖下层</div><div className="timeline-ruler" style={{ width: rulerWidth }} onPointerDown={event => seek((event.clientX - event.currentTarget.getBoundingClientRect().left) / zoom)}>{Array.from({ length: Math.floor(rulerDuration / rulerStep) + 1 }, (_, index) => <span key={index} style={{ left: index * rulerStep * zoom }}>{timelineTime(index * rulerStep)}</span>)}</div></div>
          {!sortedTracks.length && <div className="timeline-empty"><Layers3 size={26}/><span>添加轨道或从分镜导入，开始自由剪辑。</span></div>}
          {sortedTracks.map((track, index) => <div key={track.id} className={`timeline-track-row ${track.muted ? "muted" : ""} ${track.locked ? "locked" : ""}`}><div className={`timeline-track-heading ${selectedTrack === track.id ? "selected" : ""}`}><button className="timeline-track-name" onClick={() => { setSelected(""); setSelectedTrack(track.id); }}>{trackIcon(track.type)}<strong title={track.name}>{track.name}</strong></button><div><button disabled={!!busy || track.locked} title={track.muted ? "启用轨道" : "静音或隐藏轨道"} aria-label={`${track.muted ? "启用" : "静音"}轨道 ${track.name}`} onClick={() => patchTrack(track.id, { muted: !track.muted })}>{track.muted ? <VolumeX size={12}/> : <Volume2 size={12}/>}</button><button disabled={!!busy} title={track.locked ? "解锁轨道" : "锁定轨道"} aria-label={`${track.locked ? "解锁" : "锁定"}轨道 ${track.name}`} onClick={() => patchTrack(track.id, { locked: !track.locked })}>{track.locked ? <LockKeyhole size={12}/> : <UnlockKeyhole size={12}/>}</button><button disabled={!!busy || track.locked || index === 0 || sortedTracks[index - 1]?.locked} aria-label={`上移轨道 ${track.name}`} onClick={() => reorderTrack(track.id, -1)}><ArrowUp size={12}/></button><button disabled={!!busy || track.locked || index === sortedTracks.length - 1 || sortedTracks[index + 1]?.locked} aria-label={`下移轨道 ${track.name}`} onClick={() => reorderTrack(track.id, 1)}><ArrowDown size={12}/></button></div></div><div className={`timeline-lane ${track.type}`} data-timeline-track={track.id} style={{ width: rulerWidth, backgroundSize: `${rulerStep * zoom}px 100%` }} onPointerDown={event => { if (event.target === event.currentTarget) { setSelected(""); setSelectedTrack(track.id); seek((event.clientX - event.currentTarget.getBoundingClientRect().left) / zoom); } }} onDragOver={event => { if (!track.locked && !busy) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; } }} onDrop={event => { event.preventDefault(); const id = event.dataTransfer.getData("application/x-manju-timeline-asset"), asset = assets.find(item => item.id === id); if (asset && !busy) addClip(asset, track.id, (event.clientX - event.currentTarget.getBoundingClientRect().left) / zoom); }}>
            {edit.clips.filter(clip => clip.track_id === track.id).map(clip => <div key={clip.id} className={`timeline-clip ${track.type} ${selected === clip.id ? "selected" : ""} ${clip.muted ? "clip-muted" : ""} ${clip.locked ? "clip-locked" : ""}`} data-clip-id={clip.id} style={{ left: clip.start * zoom, width: Math.max(3, clip.duration * zoom) }} onPointerDown={event => beginDrag(event, clip, "move")} onPointerMove={dragMove} onPointerUp={endDrag} onPointerCancel={endDrag} title={`${clipLabel(clip)} · ${timelineTime(clip.start)} – ${timelineTime(clip.start + clip.duration)}`}><button className="timeline-trim-handle left" aria-label={`裁剪片段起点 ${clipLabel(clip)}`} disabled={!!busy || track.locked || clip.locked} onPointerDown={event => beginDrag(event, clip, "left")}/><span className="timeline-clip-icon">{trackIcon(track.type, 12)}</span><span className="timeline-clip-label">{clipLabel(clip)}<small>{clip.duration.toFixed(2)} 秒{clip.trim_start ? ` · 入点 ${clip.trim_start.toFixed(2)}` : ""}</small></span><GripVertical size={12} className="timeline-clip-grip"/><button className="timeline-trim-handle right" aria-label={`裁剪片段终点 ${clipLabel(clip)}`} disabled={!!busy || track.locked || clip.locked} onPointerDown={event => beginDrag(event, clip, "right")}/></div>)}
          </div></div>)}
          <div className="timeline-playhead" style={{ left: 172 + time * zoom }}><i/></div>
        </div>
      </div>
    </>}
    {render && <div className={`timeline-render ${render.status}`}><span>{running(render) ? <LoaderCircle size={15} className="spin"/> : <Film size={15}/>}<strong>{{pending:"等待导出",running:"正在导出",succeeded:"多轨成片已入库",failed:"导出失败"}[render.status]}</strong><small>{render.message || (render.error ? errorText(render.error) : "")}</small></span>{running(render) && <progress max={1} value={render.progress || 0}/>}<div>{render.output_version_id && <><button onClick={() => { setPlaying(false); setShowOutput(true); }}><Play size={14}/>播放多轨成片</button><a href={mediaUrl(render.output_version_id, "original", true)} download><Download size={14}/>下载 MP4</a></>}{render.status === "failed" && <button disabled={!!busy} onClick={() => void action("retry", async () => { setRender(await api<ProductionRender>(`/api/production/renders/${render.id}/retry`, { method: "POST", body: JSON.stringify({ request_id: crypto.randomUUID() }) })); })}><RefreshCw size={14}/>重试</button>}</div></div>}
  </Modal>;
}
