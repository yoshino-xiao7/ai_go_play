import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, Check, ChevronLeft, ChevronRight, Image, Library, LoaderCircle, Monitor, Music2, Search, Upload } from "lucide-react";
import { api, mediaUrl, uploadAsset } from "./api";
import type { AssetPage } from "./types";
import type { SubjectMediaCandidate } from "./subjectTypes";
import { Modal } from "./ui";

export type { SubjectMediaCandidate } from "./subjectTypes";
export type SubjectMediaSource = "local" | "library" | "canvas";
type Props = {
  kind: "image" | "audio";
  source: SubjectMediaSource;
  projectId?: string;
  canvasMedia: SubjectMediaCandidate[];
  onChoose: (candidate: SubjectMediaCandidate) => void;
  onClose: () => void;
};
type MediaChoice = SubjectMediaCandidate & { missing?: boolean; filename?: string };
const pageSize = 18;
const sourceLabels: Record<SubjectMediaSource, string> = { local: "本地文件", library: "素材库", canvas: "当前画布" };
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error);

export function useSubjectMediaUrl() {
  const [versions, setVersions] = useState<Record<string, number>>({});
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    const refresh = (event: Event) => {
      const payload = (event as CustomEvent).detail;
      if (event.type === "manju:event" && payload?.type !== "asset.updated") return;
      const version = payload?.data?.version_id;
      if (typeof version === "string") setVersions(current => ({ ...current, [version]: (current[version] || 0) + 1 }));
      else setEpoch(current => current + 1);
    };
    window.addEventListener("manju:event", refresh);
    window.addEventListener("manju:reconnected", refresh);
    return () => { window.removeEventListener("manju:event", refresh); window.removeEventListener("manju:reconnected", refresh); };
  }, []);
  return useCallback((versionId: string, variant = "thumbnail") => `${mediaUrl(versionId, variant)}&subject_rev=${epoch}.${versions[versionId] || 0}`, [epoch, versions]);
}

export default function SubjectMediaPicker({ kind, source: initialSource, projectId, canvasMedia, onChoose, onClose }: Props) {
  const media = useSubjectMediaUrl();
  const [source, setSource] = useState(initialSource);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<MediaChoice[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [dragging, setDragging] = useState(false);
  const uploadBusy = useRef(false);
  const alive = useRef(true);
  const input = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const audioElements = useRef(new Map<string, HTMLAudioElement>());
  const label = kind === "image" ? "图片" : "音频";
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => container.current?.querySelector<HTMLElement>('input:not([type="file"]),button[aria-selected="true"]')?.focus());
    return () => cancelAnimationFrame(frame);
  }, []);
  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setError("");
    if (source !== "library") { setLoading(false); return () => { disposed = true; }; }
    setLoading(true);
    setItems([]);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ type: kind, search, offset: String(page * pageSize), limit: String(pageSize), trash: "false" });
      void api<AssetPage>(`/api/assets?${params}`, { signal: controller.signal }).then(result => {
        if (disposed) return;
        setItems(result.items.filter(asset => asset.type === kind).map(asset => ({ version_id: asset.current_version_id, title: asset.name, kind, missing: asset.version.missing, filename: asset.version.filename })));
        setTotal(result.total);
        if (!result.items.length && page > 0) setPage(Math.max(0, Math.ceil(result.total / pageSize) - 1));
      }).catch(caught => { if (!disposed) setError(messageOf(caught)); }).finally(() => { if (!disposed) setLoading(false); });
    }, 120);
    return () => { disposed = true; clearTimeout(timer); controller.abort(); };
  }, [source, kind, search, page, revision]);

  const close = () => { if (!uploadBusy.current) onClose(); };
  const choose = (candidate: SubjectMediaCandidate) => {
    if (uploadBusy.current) return;
    onChoose(candidate);
    onClose();
  };
  const upload = async (file?: File) => {
    if (!file || uploadBusy.current) return;
    if (file.type && !file.type.startsWith(`${kind}/`)) { setError(`请选择${label}文件。`); return; }
    uploadBusy.current = true; setUploading(true); setProgress(0); setError("");
    try {
      const asset = await uploadAsset(file, { projectId, onProgress: percent => { if (alive.current) setProgress(percent); } });
      if (!alive.current) return;
      if (asset.type !== kind) throw new Error(`文件已导入为${asset.type === "audio" ? "音频" : asset.type === "image" ? "图片" : "视频"}，请另选${label}文件。`);
      onChoose({ version_id: asset.imported_version_id || asset.current_version_id, title: asset.name, kind });
      onClose();
    } catch (caught) { if (alive.current) setError(messageOf(caught)); }
    finally { uploadBusy.current = false; if (alive.current) setUploading(false); }
  };
  const canvasItems = canvasMedia.filter((candidate, index, all) => candidate.kind === kind && all.findIndex(item => item.kind === kind && item.version_id === candidate.version_id) === index && candidate.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const candidates: MediaChoice[] = source === "canvas" ? canvasItems.slice(page * pageSize, (page + 1) * pageSize) : items;
  const count = source === "canvas" ? canvasItems.length : total;
  const switchSource = (next: SubjectMediaSource) => {
    if (uploadBusy.current) return;
    audioElements.current.forEach(audio => audio.pause());
    setSource(next); setPage(0); setError("");
  };

  return createPortal(<Modal title={`选择主体${kind === "audio" ? "参考音频" : "图片"}`} wide onClose={close}>
    <div className="subject-media-picker" ref={container}>
      <div className="subject-media-sources" role="tablist" aria-label="素材来源">{(["local", "library", "canvas"] as SubjectMediaSource[]).map(option => <button type="button" key={option} role="tab" aria-selected={source === option} disabled={uploading} onClick={() => switchSource(option)}>{option === "local" ? <Upload size={15} /> : option === "library" ? <Library size={15} /> : <Monitor size={15} />}{sourceLabels[option]}</button>)}</div>
      {source === "local" ? <div className={`subject-media-upload ${dragging ? "dragging" : ""}`} onDragOver={event => { event.preventDefault(); if (!uploading) setDragging(true); }} onDragLeave={event => { if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget))) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files[0]); }}>
        {uploading ? <LoaderCircle size={33} className="spin" /> : <Upload size={33} strokeWidth={1.4} />}
        <strong>{uploading ? progress === 100 ? "正在校验并保存文件…" : `正在上传 ${progress}%` : `拖入${label}文件，或从电脑选择`}</strong>
        <p>{kind === "image" ? "支持 PNG、JPEG、WebP 等图片格式" : "支持 WAV、MP3、FLAC 等音频格式"}</p>
        <button type="button" className="button primary" disabled={uploading} onClick={() => input.current?.click()}><Upload size={15} />选择本地{label}</button>
        <small>文件会先保存到本地素材库，再绑定当前固定版本。</small>
        <input ref={input} type="file" accept={`${kind}/*`} hidden onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; void upload(file); }} />
      </div> : <>
        <label className="subject-media-search"><Search size={15} /><input autoFocus aria-label={`搜索${source === "canvas" ? "画布" : "素材库"}${label}`} placeholder={`搜索${label}名称`} value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} /></label>
        <div className={`subject-media-results ${kind}`} aria-busy={loading}>
          {loading ? <div className="subject-media-empty"><LoaderCircle className="spin" size={25} />正在读取{label}…</div> : !candidates.length ? <div className="subject-media-empty">{kind === "image" ? <Image size={31} /> : <Music2 size={31} />}<strong>{search ? `没有匹配的${label}` : source === "canvas" ? `当前画布还没有${label}` : `素材库还没有${label}`}</strong><span>可以切换来源，或上传本地文件。</span></div> : candidates.map(candidate => <article className="subject-media-item" key={candidate.version_id} data-version-id={candidate.version_id}>
            {kind === "image" ? <button type="button" className="subject-media-image" disabled={candidate.missing} aria-label={`选择图片 ${candidate.title}`} onClick={() => choose(candidate)}><img src={media(candidate.version_id)} alt={candidate.title} loading="lazy" draggable={false} /><span>{candidate.missing ? "原件缺失" : candidate.title}</span><Check size={16} /></button> : <><div className="subject-media-audio-heading"><Music2 size={21} /><div><strong title={candidate.title}>{candidate.title}</strong><small>{candidate.missing ? "原件缺失" : candidate.filename || "固定音频版本"}</small></div><button type="button" className="button secondary" disabled={candidate.missing} aria-label={`选择音频 ${candidate.title}`} onClick={() => choose(candidate)}>选用</button></div>{!candidate.missing && <audio controls preload="none" aria-label={`预听 ${candidate.title}`} src={media(candidate.version_id, "preview")} ref={element => { if (element) audioElements.current.set(candidate.version_id, element); else audioElements.current.delete(candidate.version_id); }} onPlay={event => audioElements.current.forEach(audio => { if (audio !== event.currentTarget) audio.pause(); })} />}</>}
          </article>)}
        </div>
        <footer className="subject-media-pagination"><span>{count} 个{label}</span><div><button type="button" title="上一页素材" disabled={!page || loading} onClick={() => setPage(value => value - 1)}><ChevronLeft size={16} /></button><span>{Math.min(page + 1, Math.max(1, Math.ceil(count / pageSize)))} / {Math.max(1, Math.ceil(count / pageSize))}</span><button type="button" title="下一页素材" disabled={(page + 1) * pageSize >= count || loading} onClick={() => setPage(value => value + 1)}><ChevronRight size={16} /></button></div></footer>
      </>}
      {error && <p className="subject-media-error" role="alert"><AlertCircle size={15} /><span>{error}</span>{source === "library" && <button type="button" onClick={() => setRevision(value => value + 1)}>重试</button>}</p>}
    </div>
    <footer className="modal-footer"><button type="button" className="button secondary" disabled={uploading} onClick={close}>取消</button></footer>
  </Modal>, document.body);
}
