import { useEffect, useRef, useState } from "react";
import { useStore } from "@xyflow/react";
import { AudioLines, Check, ChevronRight, FolderOpen, ImagePlus, LoaderCircle, MousePointer2, Pause, Pencil, Play, Plus, Upload, X } from "lucide-react";
import CanvasContextMenu from "./CanvasContextMenu";
import type { CanvasMenuItem } from "./CanvasContextMenu";
import { SubjectEditorDialog } from "./Subjects";
import SubjectMediaPicker, { useSubjectMediaUrl } from "./SubjectMediaPicker";
import type { SubjectMediaCandidate, SubjectSnapshot } from "./subjectTypes";
import SubjectInlineText from "./SubjectInlineText";
import VoiceDesignDialog from "./VoiceDesignDialog";

type Props = {
  subject: SubjectSnapshot;
  subjectId: string;
  onBeforeVoiceDesign: () => Promise<void>;
  onCreateVideo?:()=>void;
  onCreateSpeech?:()=>void;
  selected?: boolean;
  displayWidth?: number;
  locked?: boolean;
  projectId: string;
  getCanvasMedia: () => SubjectMediaCandidate[];
  onChange: (subject: SubjectSnapshot) => void;
  onPreview: (versionId: string) => void;
};
type Source = "local" | "library" | "canvas";
type Picker = { kind: "image" | "audio"; source: Source; candidates: SubjectMediaCandidate[] };
const kindNames = { character: "人物主体", scene: "场景主体", prop: "道具主体" };

export default function SubjectNodeView({ subject, subjectId, selected, displayWidth=340, locked, projectId, getCanvasMedia, onChange, onPreview, onCreateSpeech, onCreateVideo, onBeforeVoiceDesign }: Props) {
  const needsOriginal = useStore(state => displayWidth * state.transform[2] * (window.devicePixelRatio || 1) > 480);
  const media = useSubjectMediaUrl();
  const current = useRef(subject);
  current.current = subject;
  const [menu, setMenu] = useState<{ x: number; y: number; kind: "image" | "audio" } | null>(null);
  const [picker, setPicker] = useState<Picker | null>(null);
  const [editor, setEditor] = useState<"details" | "images" | "voice" | null>(null);
  const [editorMedia, setEditorMedia] = useState<SubjectMediaCandidate[]>([]);
  const [playing, setPlaying] = useState(false);
  const [loadingAudio, setLoadingAudio] = useState(false);
  const [error, setError] = useState("");
  const [designing, setDesigning] = useState(false);
  const [failedImage, setFailedImage] = useState(false);
  const audio = useRef<HTMLAudioElement>(null);
  const firstImage = subject.image_version_ids[0];
  const imageUrl = firstImage ? media(firstImage, selected || needsOriginal ? "original" : "thumbnail") : "";
  const voiceUrl = subject.voice_version_id ? media(subject.voice_version_id, "preview") : "";
  useEffect(() => { setFailedImage(false); }, [imageUrl]);
  useEffect(() => {
    const element = audio.current;
    setPlaying(false); setLoadingAudio(false); setError("");
    return () => { element?.pause(); };
  }, [voiceUrl]);
  useEffect(() => { if (locked) { setMenu(null); setPicker(null); setEditor(null); setDesigning(false); } }, [locked]);

  const edit = (section: "details" | "images" | "voice") => {
    if (locked) return;
    setEditorMedia(getCanvasMedia()); setEditor(section); setError("");
  };
  const choose = (kind: "image" | "audio", source: Source) => {
    if (locked) return;
    setMenu(null); setError("");
    if(source==="canvas"){window.dispatchEvent(new CustomEvent("manju:pick-canvas-media",{detail:{kind,onChoose:add}}));return;}
    setPicker({ kind, source, candidates: getCanvasMedia() });
  };
  const add = (candidate: SubjectMediaCandidate) => {
    if (locked) return;
    const value = current.current;
    if (candidate.kind === "image") {
      if (value.image_version_ids.includes(candidate.version_id)) return;
      if (value.image_version_ids.length >= 12) { setError("每个主体最多保存 12 张参考图。"); return; }
      onChange({ ...value, image_version_ids: [...value.image_version_ids, candidate.version_id] });
    } else if (value.kind === "character") {
      onChange({ ...value, voice_version_id: candidate.version_id, voice_name: candidate.title, voice_transcript: "" });
    }
  };
  const playVoice = async () => {
    const element = audio.current;
    if (!element) return;
    if (!element.paused) { element.pause(); setPlaying(false); return; }
    setLoadingAudio(true); setError("");
    try { await element.play(); setPlaying(true); }
    catch { setError("音频暂时无法播放，请检查原件或稍后重试。"); }
    finally { setLoadingAudio(false); }
  };
  const showMenu = (kind: "image" | "audio", button: HTMLButtonElement) => {
    if (locked) return;
    const bounds = button.getBoundingClientRect();
    setMenu({ kind, x: bounds.left, y: bounds.bottom + 7 });
  };
  const menuItems: CanvasMenuItem[] = menu ? [
    ...(menu.kind === "audio" ? [
      { id: "voice-design", label: "设计角色音色", icon: <AudioLines />, onSelect: () => { setMenu(null); setDesigning(true); } },
      { id: "native-video", label: "用此角色生成原生音画", icon: <Play />, onSelect: () => { setMenu(null); onCreateVideo?.(); } },
      { id: "design-divider", divider: true },
    ] : []),
    { id: "local", label: "本地添加", icon: <Upload />, onSelect: () => choose(menu.kind, "local") },
    { id: "library", label: "从资产库选择", icon: <FolderOpen />, onSelect: () => choose(menu.kind, "library") },
    { id: "canvas", label: "从画布选择", icon: <MousePointer2 />, onSelect: () => choose(menu.kind, "canvas") },
    ...(menu.kind === "audio" && subject.voice_version_id ? [
      { id: "voice-divider", divider: true },
      { id: "voice-generate", label: "生成独立配音", icon: <AudioLines />, onSelect: () => {setMenu(null);onCreateSpeech?.();} },
      { id: "voice-details", label: "编辑音色名称与参考原文", icon: <Pencil />, onSelect: () => edit("voice") },
      { id: "voice-remove", label: "解除音色绑定", icon: <X />, onSelect: () => onChange({ ...current.current, voice_version_id: null, voice_name: "", voice_transcript: "" }) },
    ] : []),
  ] : [];

  return <div className={`subject-node-content ${selected ? "selected" : ""}`} data-subject-kind={subject.kind}>
    <div className="subject-node-title-row">
      <SubjectInlineText kind="name" value={subject.name} placeholder="主体名称" locked={locked} onSave={name=>onChange({...current.current,name})} />
      {subject.kind === "character" && <button className={`subject-voice-button nodrag nopan ${subject.voice_version_id ? "bound" : ""}`} aria-label={subject.voice_version_id ? "管理主体音色" : "绑定主体音色"} title={subject.voice_version_id ? `音色：${subject.voice_name || "已绑定参考音频"}` : "绑定人物音色"} disabled={locked} aria-expanded={menu?.kind === "audio"} onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()} onClick={event => showMenu("audio", event.currentTarget)}><AudioLines size={18} />{subject.voice_version_id && <i />}</button>}
    </div>
    <SubjectInlineText kind="description" value={subject.description} placeholder="添加外观、环境与细节描述…" locked={locked} onSave={description=>onChange({...current.current,description})} />
    <div className="subject-image-board">
      {firstImage ? <div className="subject-primary-image" role="button" tabIndex={0} aria-label="预览主体主图" onDoubleClick={event => { event.stopPropagation(); onPreview(firstImage); }} onKeyDown={event => { if (event.key === "Enter") { event.stopPropagation(); onPreview(firstImage); } }}>
        {!failedImage ? <img src={imageUrl} loading="lazy" decoding="async" alt={`${subject.name}主图`} draggable={false} onError={() => setFailedImage(true)} /> : <div className="subject-image-missing"><ImagePlus size={26} /><span>图片暂不可预览</span></div>}
        <span className="subject-primary-label">主参考</span>
      </div> : <button className="subject-empty-image nodrag nopan" disabled={locked} onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()} onClick={event => showMenu("image", event.currentTarget)}><ImagePlus size={30} strokeWidth={1.3} /><span>添加主体参考图</span><small>人物设定、场景或道具</small></button>}
      {firstImage && <button className="subject-image-add nodrag nopan" title="添加主体参考图" aria-label="添加主体参考图" disabled={locked || subject.image_version_ids.length >= 12} aria-expanded={menu?.kind === "image"} onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()} onClick={event => showMenu("image", event.currentTarget)}><Plus size={27} strokeWidth={1.4} /></button>}
    </div>
    {subject.image_version_ids.length > 1 && <div className="subject-image-strip nodrag nopan nowheel" aria-label="主体参考图" onPointerDown={event => event.stopPropagation()}>{subject.image_version_ids.map((versionId, index) => <div className={index === 0 ? "primary" : ""} key={versionId}>
      <button title={index === 0 ? "当前主参考图" : `将参考图 ${index + 1} 设为主图`} aria-label={index === 0 ? "当前主参考图" : `将参考图 ${index + 1} 设为主图`} disabled={locked} onClick={() => { if (index > 0) onChange({ ...current.current, image_version_ids: [versionId, ...current.current.image_version_ids.filter(id => id !== versionId)] }); }}><img src={media(versionId)} alt={`参考图 ${index + 1}`} draggable={false} />{index === 0 && <Check size={10} />}</button>
      {!locked && <button className="subject-image-remove" title={`移除参考图 ${index + 1}`} aria-label={`移除参考图 ${index + 1}`} onClick={() => onChange({ ...current.current, image_version_ids: current.current.image_version_ids.filter(id => id !== versionId) })}><X size={9} /></button>}
    </div>)}</div>}
    {subject.kind === "character" && subject.voice_version_id && <div className="subject-voice-strip nodrag nopan nowheel" onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}>
      <audio key={subject.voice_version_id} ref={audio} preload="none" src={voiceUrl} onEnded={() => setPlaying(false)} onPause={() => setPlaying(false)} onError={() => { setPlaying(false); setLoadingAudio(false); setError("音频暂时无法播放，请检查素材原件。"); }} />
      <button className="subject-voice-play" aria-label={playing ? "暂停主体音色" : "试听主体音色"} title={playing ? "暂停" : "试听音色参考"} disabled={loadingAudio} onClick={() => void playVoice()}>{loadingAudio ? <LoaderCircle className="spin" size={13} /> : playing ? <Pause size={13} /> : <Play size={13} />}</button>
      <AudioLines size={15} /><span title={subject.voice_name || "音色参考"}>{subject.voice_name || "音色参考"}</span><button className="subject-voice-edit" title="编辑音色绑定" disabled={locked} onClick={() => edit("voice")}><ChevronRight size={13} /></button>
    </div>}
    <div className="subject-node-meta"><span>{kindNames[subject.kind]}</span><button className="nodrag nopan" title="管理主体参考图" disabled={locked} onPointerDown={event => event.stopPropagation()} onClick={() => edit("images")}>{subject.image_version_ids.length} 张参考图<Pencil size={10} /></button></div>
    {error && <div className="subject-node-error" role="alert">{error}<button className="nodrag" title="关闭主体提示" onClick={() => setError("")}><X size={12} /></button></div>}
    {menu && <CanvasContextMenu position={menu} items={menuItems} onClose={() => setMenu(null)} />}
    {picker && <SubjectMediaPicker kind={picker.kind} source={picker.source} projectId={projectId} canvasMedia={picker.candidates} onChoose={add} onClose={() => setPicker(null)} />}
    {editor && <SubjectEditorDialog docked initial={subject} initialSection={editor} projectId={projectId} canvasMedia={editorMedia} onClose={() => setEditor(null)} onSave={next => { if (!locked) onChange(next); setEditor(null); }} />}
    {designing && !locked && <VoiceDesignDialog projectId={projectId} subjectId={subjectId} subject={subject} onBeforeSubmit={onBeforeVoiceDesign} onClose={() => setDesigning(false)} onAdopt={voice => { if (!locked && current.current.kind === "character") onChange({ ...current.current, ...voice }); }} />}
  </div>;
}
