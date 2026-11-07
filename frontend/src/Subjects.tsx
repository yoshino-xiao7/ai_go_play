import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, ArrowLeft, ArrowRight, Box, ChevronLeft, ChevronRight, Image, Images, Mountain, Library, LoaderCircle, Mic, Monitor, Pencil, Plus, Search, Trash2, Upload, UserRound, X } from "lucide-react";
import { api } from "./api";
import { Confirm, Modal } from "./ui";
import type { Subject, SubjectKind, SubjectMediaCandidate, SubjectPage, SubjectSnapshot } from "./subjectTypes";
import { subjectKindLabels, subjectSnapshot } from "./subjectTypes";
import SubjectMediaPicker, { useSubjectMediaUrl } from "./SubjectMediaPicker";
import type { SubjectMediaSource } from "./SubjectMediaPicker";
import "./subjects.css";

export const SUBJECT_DRAG_TYPE = "application/x-manju-subject";
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error);
const emptyMedia: SubjectMediaCandidate[] = [];
const kinds: SubjectKind[] = ["character", "scene", "prop"];
const kindIcon = (kind: SubjectKind, size = 15) => kind === "character" ? <UserRound size={size} /> : kind === "scene" ? <Mountain size={size} /> : <Box size={size} />;

function normalizeSnapshot(initial: SubjectSnapshot): SubjectSnapshot {
  const kind = kinds.includes(initial.kind) ? initial.kind : "character";
  return {
    ...initial, kind, name: initial.name || "", description: initial.description || "",
    image_version_ids: [...new Set(initial.image_version_ids || [])],
    voice_version_id: kind === "character" ? initial.voice_version_id || null : null,
    voice_name: kind === "character" ? initial.voice_name || "" : "",
    voice_transcript: kind === "character" ? initial.voice_transcript || "" : "",
  };
}

export function SaveSubjectDialog({ versionId, name = "", description = "", snapshot, initial, projectId, canvasMedia, onClose, onSaved }: {
  versionId?: string;
  name?: string;
  description?: string;
  snapshot?: SubjectSnapshot;
  initial?: SubjectSnapshot;
  projectId?: string;
  canvasMedia?: SubjectMediaCandidate[];
  onClose: () => void;
  onSaved: (subject: Subject) => void;
}) {
  const attempt = useRef<{ key: string; fingerprint: string } | null>(null);
  const save = async (value: SubjectSnapshot) => {
    const fingerprint = JSON.stringify(subjectPayload(value));
    if (!attempt.current || attempt.current.fingerprint !== fingerprint) attempt.current = { key: crypto.randomUUID(), fingerprint };
    const subject = await api<Subject>("/api/subjects", { method: "POST", body: fingerprint, headers: { "X-Request-ID": attempt.current.key } });
    onSaved(subject);
  };
  return <SubjectEditorDialog initial={snapshot || initial || { kind: "character", name, description, image_version_ids: versionId ? [versionId] : [] }} projectId={projectId} canvasMedia={canvasMedia} onClose={onClose} onSave={save} title="保存到主体库" saveLabel="保存主体" requireImages />;
}

function subjectPayload(snapshot: SubjectSnapshot) {
  return {
    kind: snapshot.kind, name: snapshot.name.trim(), description: snapshot.description,
    image_version_ids: snapshot.image_version_ids,
    voice_version_id: snapshot.kind === "character" ? snapshot.voice_version_id || null : null,
    voice_name: snapshot.kind === "character" ? snapshot.voice_name || "" : "",
    voice_transcript: snapshot.kind === "character" ? snapshot.voice_transcript || "" : "",
  };
}

export function SubjectEditorDialog({ docked=false, initial, projectId, canvasMedia = emptyMedia, initialSection = "details", onClose, onSave, title = "编辑主体", saveLabel = "保存修改", requireImages = false }: {
  initial: SubjectSnapshot;
  projectId?: string;
  canvasMedia?: SubjectMediaCandidate[];
  docked?: boolean;
  initialSection?: "details" | "images" | "voice";
  onClose: () => void;
  onSave: (snapshot: SubjectSnapshot) => void | Promise<void>;
  title?: string;
  saveLabel?: string;
  requireImages?: boolean;
}) {
  const [draft, setDraft] = useState(() => normalizeSnapshot(initial));
  const media = useSubjectMediaUrl();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [failedPreviews, setFailedPreviews] = useState<Set<string>>(new Set());
  const [picker, setPicker] = useState<{ kind: "image" | "audio"; source: SubjectMediaSource } | null>(null);
  const submitting = useRef(false);
  const alive = useRef(true);
  const sectionRoot = useRef<HTMLDivElement>(null);
  useEffect(() => {
    alive.current = true;
    const frame = requestAnimationFrame(() => {
      const section = sectionRoot.current?.querySelector<HTMLElement>(`[data-subject-section="${initialSection}"]`);
      section?.scrollIntoView({ block: "nearest" });
      if (initialSection !== "details") section?.querySelector<HTMLElement>("button:not([disabled]),input,textarea")?.focus();
    });
    return () => { alive.current = false; cancelAnimationFrame(frame); };
  }, [initialSection]);
  const patch = (value: Partial<SubjectSnapshot>) => setDraft(current => ({ ...current, ...value }));
  const close = () => { if (!submitting.current && !picker) onClose(); };
  const changeKind = (kind: SubjectKind) => patch({ kind, ...(kind !== "character" ? { voice_version_id: null, voice_name: "", voice_transcript: "" } : {}) });
  const selectMedia = (candidate: SubjectMediaCandidate) => {
    setError("");
    if (candidate.kind === "image") {
      setDraft(current => current.image_version_ids.includes(candidate.version_id) || current.image_version_ids.length >= 12 ? current : { ...current, image_version_ids: [...current.image_version_ids, candidate.version_id] });
    } else patch({ voice_version_id: candidate.version_id, voice_name: candidate.title, voice_transcript: "" });
  };
  const reorderImage = (index: number, direction: number) => {
    const images = [...draft.image_version_ids];
    const next = index + direction;
    if (next < 0 || next >= images.length) return;
    [images[index], images[next]] = [images[next], images[index]];
    patch({ image_version_ids: images });
  };
  const save = async () => {
    if (submitting.current || picker || !draft.name.trim()) return;
    if (requireImages && !draft.image_version_ids.length) { setError("保存到主体库至少需要一张图片，请先添加主体图片。"); return; }
    if (draft.image_version_ids.length > 12) { setError("每个主体最多保存 12 张图片，请移除多余图片。"); return; }
    submitting.current = true; setBusy(true); setError("");
    try { await onSave({ ...normalizeSnapshot(draft), name: draft.name.trim() }); }
    catch (caught) { if (alive.current) setError(messageOf(caught)); }
    finally { submitting.current = false; if (alive.current) setBusy(false); }
  };
  const sources = (kind: "image" | "audio") => <div className="subject-editor-sources">
    <button type="button" disabled={busy || (kind === "image" && draft.image_version_ids.length >= 12)} onClick={() => setPicker({ kind, source: "local" })}><Upload size={13} />本地上传</button>
    <button type="button" disabled={busy || (kind === "image" && draft.image_version_ids.length >= 12)} onClick={() => setPicker({ kind, source: "library" })}><Library size={13} />素材库</button>
    <button type="button" disabled={busy || (kind === "image" && draft.image_version_ids.length >= 12)} onClick={() => docked ? window.dispatchEvent(new CustomEvent("manju:pick-canvas-media",{detail:{kind,onChoose:selectMedia}})) : setPicker({ kind, source: "canvas" })}><Monitor size={13} />当前画布</button>
  </div>;
  return createPortal(<div className={docked?"subject-editor-dock":undefined}>
    <Modal title={title} wide onClose={close}>
      <form className="subject-editor" onSubmit={event => { event.preventDefault(); void save(); }}>
        <div className="subject-editor-content" ref={sectionRoot}>
          <section className="subject-editor-details" data-subject-section="details">
            <div className="subject-kind-options" role="group" aria-label="主体类型">{kinds.map(kind => <button key={kind} type="button" aria-pressed={draft.kind === kind} disabled={busy} onClick={() => changeKind(kind)}>{kindIcon(kind)}{subjectKindLabels[kind]}</button>)}</div>
            <label>主体名称<input autoFocus aria-label="主体名称" value={draft.name} maxLength={250} required disabled={busy} onChange={event => patch({ name: event.target.value })} placeholder={draft.kind === "character" ? "例如：角色 · 雪凉" : draft.kind === "scene" ? "例如：黄昏的街角" : "例如：蓝色魔法书"} /></label>
            <label>描述<textarea aria-label="主体描述" value={draft.description} maxLength={6000} rows={3} disabled={busy} onChange={event => patch({ description: event.target.value })} placeholder={draft.kind === "character" ? "记录人物外观、服装、性格与表情特征…" : draft.kind === "scene" ? "记录场景布局、光线、时间和氛围…" : "记录道具的材质、形状、颜色与细节…"} /></label>
          </section>
          <section className="subject-editor-section" data-subject-section="images" aria-label="主体图片">
            <header><div><Images size={16} /><strong>主体图片</strong><span>{draft.image_version_ids.length} / 12</span></div>{sources("image")}</header>
            <p className="subject-section-hint">第一张用作封面，多张图片可以记录不同角度、表情或细节。</p>
            {draft.image_version_ids.length ? <div className="subject-editor-images">{draft.image_version_ids.map((versionId, index) => <article className="subject-editor-image" key={versionId} data-version-id={versionId}>
              {failedPreviews.has(media(versionId)) ? <div className="subject-image-unavailable"><Image size={22} /><span>暂不可预览</span></div> : <img src={media(versionId)} alt={`主体图片 ${index + 1}`} draggable={false} onError={() => setFailedPreviews(current => new Set(current).add(media(versionId)))} />}
              <span className="subject-image-number">{index === 0 ? "封面" : index + 1}</span>
              <button type="button" className="subject-image-remove" title={`移除主体图片 ${index + 1}`} aria-label={`移除主体图片 ${index + 1}`} disabled={busy} onClick={() => patch({ image_version_ids: draft.image_version_ids.filter(item => item !== versionId) })}><X size={13} /></button>
              <div className="subject-image-order"><button type="button" title={`前移主体图片 ${index + 1}`} aria-label={`前移主体图片 ${index + 1}`} disabled={busy || index === 0} onClick={() => reorderImage(index, -1)}><ArrowLeft size={13} /></button><button type="button" title={`后移主体图片 ${index + 1}`} aria-label={`后移主体图片 ${index + 1}`} disabled={busy || index === draft.image_version_ids.length - 1} onClick={() => reorderImage(index, 1)}><ArrowRight size={13} /></button></div>
            </article>)}</div> : <div className="subject-editor-empty"><Images size={27} strokeWidth={1.5} /><span>{requireImages ? "添加至少一张图片后保存到主体库" : "可以先保存主体设定，稍后再添加图片"}</span></div>}
          </section>
          {draft.kind === "character" && <section className="subject-editor-section subject-editor-voice" data-subject-section="voice" aria-label="人物音色">
            <header><div><Mic size={16} /><strong>人物音色</strong><span>可选</span></div>{sources("audio")}</header>
            <p className="subject-section-hint">绑定参考音频与对应文本，随人物设定一起保存。</p>
            {draft.voice_version_id ? <div className="subject-voice-preview"><audio controls preload="metadata" aria-label="预听人物音色" src={media(draft.voice_version_id, "preview")} /><button type="button" aria-label="移除人物音色" title="移除人物音色" disabled={busy} onClick={() => patch({ voice_version_id: null, voice_name: "", voice_transcript: "" })}><Trash2 size={15} /></button></div> : <div className="subject-voice-empty"><Mic size={17} /><span>还没有绑定参考音频</span></div>}
            <label>音色名称<input aria-label="音色名称" maxLength={250} value={draft.voice_name || ""} disabled={busy} onChange={event => patch({ voice_name: event.target.value })} placeholder="例如：雪凉 · 清澈少女音" /></label>
            <label>参考音频对应文本<textarea aria-label="音色参考文本" maxLength={6000} rows={3} value={draft.voice_transcript || ""} disabled={busy} onChange={event => patch({ voice_transcript: event.target.value })} placeholder="填写参考音频中实际说出的内容…" /></label>
          </section>}
        </div>
        {error && <p className="subject-error" role="alert"><AlertCircle size={14} />{error}</p>}
        <footer className="modal-footer subject-editor-footer"><span>{requireImages ? "素材使用固定版本，原件保留在本地" : "保存当前主体设定"}</span><button type="button" className="button secondary" disabled={busy} onClick={close}>取消</button><button type="submit" className="button primary" disabled={busy || !draft.name.trim()}>{busy ? <LoaderCircle size={15} className="spin" /> : kindIcon(draft.kind)}{busy ? "保存中…" : saveLabel}</button></footer>
      </form>
    </Modal>
    {picker && <SubjectMediaPicker kind={picker.kind} source={picker.source} projectId={projectId} canvasMedia={canvasMedia} onChoose={selectMedia} onClose={() => setPicker(null)} />}
  </div>, document.body);
}

export default function SubjectLibrary({ onChoose, refresh = 0 }: { onChoose: (subject: Subject) => void; refresh?: number }) {
  const media = useSubjectMediaUrl();
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<SubjectKind | "">("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<SubjectPage>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<Subject | null>(null);
  const [removing, setRemoving] = useState<Subject | null>(null);
  const [deleting, setDeleting] = useState(false);
  const deleteBusy = useRef(false);
  useEffect(() => {
    let disposed = false;
    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ search, offset: String(page * 30), limit: "30" });
      if (kind) params.set("kind", kind);
      void api<SubjectPage>(`/api/subjects?${params}`, { signal: controller.signal }).then(result => {
        if (disposed) return;
        setData(result); setError("");
        if (!result.items.length && page > 0) setPage(Math.max(0, Math.ceil(result.total / 30) - 1));
      }).catch(caught => { if (!disposed) setError(messageOf(caught)); }).finally(() => { if (!disposed) setLoading(false); });
    }, 120);
    return () => { disposed = true; clearTimeout(timer); controller.abort(); };
  }, [search, kind, page, refresh, revision]);
  const remove = async () => {
    if (!removing || deleteBusy.current) return;
    deleteBusy.current = true; setDeleting(true); setError("");
    try { await api(`/api/subjects/${removing.id}`, { method: "DELETE" }); setRemoving(null); setRevision(value => value + 1); }
    catch (caught) { setError(messageOf(caught)); setRemoving(null); }
    finally { deleteBusy.current = false; setDeleting(false); }
  };
  return <div className="subject-library">
    <label className="canvas-search"><Search size={14} /><input aria-label="搜索主体" placeholder="搜索人物、场景或道具" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} /></label>
    <div className="subject-library-kinds" role="group" aria-label="筛选主体类型"><button type="button" aria-pressed={!kind} onClick={() => { setKind(""); setPage(0); }}>全部</button>{kinds.map(item => <button type="button" key={item} aria-pressed={kind === item} onClick={() => { setKind(item); setPage(0); }}>{kindIcon(item, 12)}{subjectKindLabels[item]}</button>)}</div>
    {error && <p className="subject-error" role="alert"><AlertCircle size={14} />{error}<button onClick={() => setRevision(value => value + 1)}>重试</button></p>}
    <div className="subject-library-list">
      {loading && !data.items.length ? <div className="subject-library-empty"><LoaderCircle className="spin" size={22} />读取主体…</div> : !data.items.length ? <div className="subject-library-empty">{kind ? kindIcon(kind, 30) : <UserRound size={30} strokeWidth={1.4} />}<strong>{search || kind ? "没有找到主体" : "把常用角色收在这里"}</strong><p>{search || kind ? "试试其他名称、描述或类型。" : "右击图片或主体卡片，选择“保存到主体库”。人物、场景和道具都可以重复使用。"}</p></div> : data.items.map(subject => {
        const snapshot = subjectSnapshot(subject);
        const missing = subject.images?.some(image => image.missing) || subject.version?.missing;
        return <article key={subject.id} className="subject-library-card" data-subject-id={subject.id} draggable={!missing} onDragStart={event => { event.dataTransfer.setData(SUBJECT_DRAG_TYPE, JSON.stringify(subject)); event.dataTransfer.effectAllowed = "copy"; }}>
          <div className="subject-library-thumb"><img src={media(snapshot.image_version_ids[0] || subject.version_id)} alt={subject.name} draggable={false} loading="lazy" />{missing && <span className="subject-missing">原件缺失</span>}<div className="subject-library-badges"><span>{kindIcon(snapshot.kind, 11)}{subjectKindLabels[snapshot.kind]}</span>{snapshot.image_version_ids.length > 1 && <span><Images size={11} />{snapshot.image_version_ids.length} 张</span>}{snapshot.voice_version_id && <span title={subject.voice?.missing ? "参考音频原件缺失" : snapshot.voice_name || "已绑定参考音频"}><Mic size={11} />{subject.voice?.missing ? "音频缺失" : "音色"}</span>}</div><button title={`添加主体 ${subject.name}`} disabled={!!missing} onClick={() => onChoose(subject)}><Plus size={16} /></button></div>
          <div className="subject-library-info"><strong title={subject.name}>{subject.name}</strong>{subject.description && <p title={subject.description}>{subject.description}</p>}<div><span>拖入画布使用</span><button title={`编辑主体 ${subject.name}`} onClick={() => setEditing(subject)}><Pencil size={12} /></button><button title={`移除主体 ${subject.name}`} onClick={() => setRemoving(subject)}><Trash2 size={12} /></button></div></div>
        </article>;
      })}
    </div>
    <footer className="subject-library-footer"><span>{data.total} 个主体</span>{data.total > 30 && <div><button title="上一页主体" disabled={!page} onClick={() => setPage(value => value - 1)}><ChevronLeft size={14} /></button><span>{page + 1} / {Math.ceil(data.total / 30)}</span><button title="下一页主体" disabled={(page + 1) * 30 >= data.total} onClick={() => setPage(value => value + 1)}><ChevronRight size={14} /></button></div>}</footer>
    {editing && <SubjectEditorDialog initial={subjectSnapshot(editing)} requireImages onClose={() => setEditing(null)} onSave={async snapshot => { await api<Subject>(`/api/subjects/${editing.id}`, { method: "PATCH", body: JSON.stringify(subjectPayload(snapshot)) }); setEditing(null); setRevision(value => value + 1); }} />}
    {removing && createPortal(<Confirm title="从主体库移除" description={`移除“${removing.name}”的主体条目。已有画布主体和资产原件会继续保留。`} busy={deleting} onClose={() => { if (!deleteBusy.current) setRemoving(null); }} onConfirm={() => void remove()} />, document.body)}
  </div>;
}
