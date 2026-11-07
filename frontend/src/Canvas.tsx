import StudioSelect from "./StudioSelect";
import { useRightButtonPan } from "./useRightButtonPan";
import ImageViewer from "./ImageViewer";
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Handle,
  Position,
  NodeResizer,
  ConnectionLineType,
  SelectionMode,
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  reconnectEdge,
  useReactFlow,
  useViewport,
  useStore,
  useNodeConnections,
} from "@xyflow/react";
import type {
  Node,
  Edge,
  NodeProps,
  NodeChange,
  EdgeChange,
  Connection,
  Viewport,
} from "@xyflow/react";
import {
  ArrowLeft,
  Brush,
  Check,
  CircuitBoard,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Ellipsis,
  Copy,
  ClipboardPaste,
  Download,
  Expand,
  FolderOpen,
  FolderInput,
  Frame,
  Group,
  Image as ImageIcon,
  Images,
  Lock,
  Maximize,
  Minus,
  MousePointer2,
  Music2,
  PanelLeft,
  PanelRight,
  Pencil,
  Plus,
  Redo2,
  Search,
  ListChecks,
  Sparkles,
  SlidersHorizontal,
  Trash2,
  Type,
  Undo2,
  Ungroup,
  Unlock,
  Upload,
  UserRoundPlus,
  UserRound,
  Mountain,
  Package,
  Video,
  X,
  AlignLeft,
  AlignCenterHorizontal,
  AlignRight,
  AlignStartVertical,
  AlignCenterVertical,
  AlignEndVertical,
  BetweenHorizontalStart,
  BetweenVerticalStart,
  Loader2,
  AlertCircle,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { api, uploadAsset, mediaUrl } from "./api";
import type { Asset, AssetVersion, Project } from "./types";
import { Confirm } from "./ui";
import CanvasContextMenu from "./CanvasContextMenu";
import type { CanvasMenuItem } from "./CanvasContextMenu";
import { parseClipboardText, readCanvasClipboard } from "./clipboardHelpers";
import SubjectLibrary, {
  SaveSubjectDialog,
  SUBJECT_DRAG_TYPE,
} from "./Subjects";
import { subjectSnapshot } from "./subjectTypes";
import type {
  Subject,
  SubjectKind,
  SubjectMediaCandidate,
  SubjectSnapshot,
} from "./subjectTypes";
import SubjectNodeView from "./SubjectNodeView";
import SaveToCanvasDialog, { cloneCanvasSelection, mergeCanvasSelection } from "./SaveToCanvasDialog";
import DraftRecovery from "./DraftRecovery";
import CanvasProjectMenu from "./CanvasProjectMenu";
import type { RecoverableCanvas } from "./DraftRecovery";
import ProductionPanel from "./ProductionPanel";
import CanvasRunPanel from "./CanvasRunPanel";
import TimelineEditor from "./TimelineEditor";
import LipSyncPanel from "./LipSyncPanel";
import GenerationComposer, {
  defaultGenerationDraft,
} from "./GenerationComposer";
import AudioComposer, {defaultSpeechDraft} from "./AudioComposer";
import VideoComposer, { defaultVideoDraft } from "./VideoComposer";
import VideoViewer from "./VideoViewer";
import {GenerationProgress, useGenerationJob} from "./GenerationProgress";
import type {
  GenerationDraft,
  ImageHistoryItem,
  ImageReference,
} from "./generationTypes";
import "@xyflow/react/dist/style.css";
import "./canvas.css";
import CandidateReview from "./CandidateReview";
import "./review-experience.css";
import { canReference, edgeLocked, edgeRole, reconcileReferences } from "./canvasReferences";

type CanvasData = Record<string, unknown> & {
  title?: string;
  text?: string;
  note?: string;
  kind?: string;
  asset_version_id?: string;
  locked?: boolean;
  collapsed?: boolean;
  color?: string;
  generation?: GenerationDraft;
  generation_id?: string;
  image_history?: ImageHistoryItem[];
  subject?: SubjectSnapshot;
};
type CanvasNode = Node<CanvasData>;
type CanvasDocument = {
  revision: number;
  nodes: CanvasNode[];
  edges: Edge[];
  viewport: Viewport;
};
type SaveRequest = CanvasDocument & { request_id: string };
type PendingSave = { document: SaveRequest; localVersion: number };
type Snapshot = { nodes: CanvasNode[]; edges: Edge[] };
type MenuState = {
  x: number;
  y: number;
  position: { x: number; y: number };
  kind: "node" | "pane";
};
type CanvasProps = {
  project: Project;
  onBack: () => void;
  onProjectChange: (project: Project) => void;
  onPreview: (versionId: string) => void;
  assetsRefresh: number;
  onAssetsChange: () => void;
  onOpenComfy: () => void;
  onOpenTasks: () => void;
};
type CanvasActions = {
  projectId: string;
  flushCanvas: () => Promise<void>;
  getCanvasMedia: () => SubjectMediaCandidate[];
  preview: (versionId: string) => void;
  updateSubject: (id: string, snapshot: SubjectSnapshot) => void;
  beginEdit: () => void;
  updateData: (id: string, patch: Partial<CanvasData>) => void;
  toggleGroup: (id: string) => void;
  resizeStart: () => void;
  resizeEnd: () => void;
};
const Actions = createContext<CanvasActions | null>(null);
const MediaRevisions = createContext<Record<string, number>>({});
const initialViewport = { x: 80, y: 70, zoom: 1 };
const assetDragType = "application/x-manju-asset";
const uid = () => crypto.randomUUID();
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
const subjectKindNames: Record<SubjectKind, string> = {
  character: "人物主体",
  scene: "场景主体",
  prop: "道具主体",
};
const subjectKindIcons = {
  character: UserRound,
  scene: Mountain,
  prop: Package,
};
const isImageReferenceNode = (node: CanvasNode) =>
  (node.type === "media" || node.type === "subject") &&
  node.data.kind === "image";

function cleanNodes(nodes: CanvasNode[]): CanvasNode[] {
  return nodes.map(
    ({
      selected: _selected,
      dragging: _dragging,
      measured: _measured,
      resizing: _resizing,
      ...node
    }) => node,
  );
}

function dimensions(node: CanvasNode) {
  return {
    width: Number(
      node.width ?? node.style?.width ?? node.measured?.width ?? 260,
    ),
    height: Number(
      node.height ?? node.style?.height ?? node.measured?.height ?? 200,
    ),
  };
}

function absolutePosition(
  node: CanvasNode,
  nodes: CanvasNode[],
): { x: number; y: number } {
  let x = node.position.x;
  let y = node.position.y;
  let parentId = node.parentId;
  const visited = new Set([node.id]);
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    const parent = nodes.find((item) => item.id === parentId);
    if (!parent) break;
    x += parent.position.x;
    y += parent.position.y;
    parentId = parent.parentId;
  }
  return { x, y };
}

function isDescendant(node: CanvasNode, parentId: string, nodes: CanvasNode[]) {
  let next = node.parentId;
  const visited = new Set<string>();
  while (next && !visited.has(next)) {
    if (next === parentId) return true;
    visited.add(next);
    next = nodes.find((item) => item.id === next)?.parentId;
  }
  return false;
}

function NodeChrome({
  selected,
  data,
  children,
  className = "",
}: NodeProps<CanvasNode> & { children: React.ReactNode; className?: string }) {
  const actions = useContext(Actions)!;
  const subject = !!data.subject;
  const incoming = useNodeConnections({ handleType: "target" });
  const outgoing = useNodeConnections({ handleType: "source" });
  return (
    <div
      className={`canvas-node ${className} ${selected ? "is-selected" : ""} ${data.locked ? "is-locked" : ""}`}
    >
      <NodeResizer
        isVisible={selected && !data.locked && !data.collapsed}
        minWidth={subject ? 260 : 150}
        minHeight={subject ? 400 : 90}
        onResizeStart={actions.resizeStart}
        onResizeEnd={actions.resizeEnd}
      />
      {children}
      {data.locked && (
        <span className="node-lock">
          <Lock size={12} />
        </span>
      )}
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        className={`nodrag nopan ${incoming.length ? "is-connected" : ""}`}
        title="连接到此卡片：点击或拖动连线"
        aria-label="连接到此卡片"
      >
        <Plus size={12} strokeWidth={1.7} />
      </Handle>
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        className={`nodrag nopan ${outgoing.length ? "is-connected" : ""}`}
        title="从此卡片连接：点击或拖动连线"
        aria-label="从此卡片连接"
      >
        <Plus size={12} strokeWidth={1.7} />
      </Handle>
    </div>
  );
}

function NodeHeading({
  id,
  data,
  icon,
  fallback = "未命名素材",
}: {
  id: string;
  data: CanvasData;
  icon: React.ReactNode;
  fallback?: string;
}) {
  const actions = useContext(Actions)!;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const cancelled = useRef(false);
  const commit = () => {
    if (
      !cancelled.current &&
      !data.locked &&
      name.trim() !== (data.title || "")
    ) {
      actions.beginEdit();
      actions.updateData(id, { title: name.trim() || fallback });
    }
    setEditing(false);
  };
  return (
    <div className="media-node-caption node-heading-caption">
      <span className="node-heading-icon">{icon}</span>
      {editing ? (
        <input
          className="node-heading-input nodrag nopan"
          aria-label="编辑节点名称"
          value={name}
          maxLength={250}
          autoFocus
          onFocus={(event) => event.target.select()}
          onChange={(event) => setName(event.target.value)}
          onBlur={commit}
          onPointerDown={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => {
            event.stopPropagation();
            if (event.nativeEvent.isComposing) return;
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              cancelled.current = true;
              setEditing(false);
            }
          }}
        />
      ) : (
        <span className="node-heading-name" title={data.title || fallback}>
          {data.title || fallback}
        </span>
      )}
      {!editing && !data.locked && (
        <button
          className="node-heading-rename nodrag nopan"
          title="重命名节点"
          aria-label="重命名节点"
          onPointerDown={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            cancelled.current = false;
            setName(data.title || "");
            setEditing(true);
          }}
        >
          <Pencil size={12} />
        </button>
      )}
      {data.locked && <Lock size={11} />}
    </div>
  );
}

const MediaNode = memo(function MediaNode(props: NodeProps<CanvasNode>) {
  const { data } = props;
  const generationJob = useGenerationJob(data.generation?.last_job_id);
  const needsOriginal = useStore(state =>
    Math.max(props.width || 264, props.height || 220) * state.transform[2] * (window.devicePixelRatio || 1) > 480,
  );
  const actions = useContext(Actions)!;
  const [showHistory, setShowHistory] = useState(false);
  const [previewVersion,setPreviewVersion]=useState<string>();
  const [largePreview,setLargePreview]=useState<string>();
  const [playing,setPlaying]=useState(false);
  useEffect(()=>{if(!props.selected)setPlaying(false);},[props.selected]);
  const imageHistory = (data.image_history || []).filter(
    (item, index, items) =>
      items.findIndex((other) => other.version_id === item.version_id) ===
      index,
  );
  if (
    (["image","video","audio"].includes(data.kind||"")) &&
    data.asset_version_id &&
    !imageHistory.some((item) => item.version_id === data.asset_version_id)
  )
    imageHistory.push({ version_id: data.asset_version_id });
  const currentHistoryIndex = imageHistory.findIndex(
    (item) => item.version_id === data.asset_version_id,
  );
  useEffect(() => {
    if (!props.selected) setShowHistory(false);
  }, [props.selected]);
  const adopt = (id:string) => {
    if(data.locked) return;
    actions.beginEdit();
    actions.updateData(props.id,{asset_version_id:id,generation_id:imageHistory.find(item=>item.version_id===id)?.job_id,image_history:imageHistory.map(item=>item.version_id===id?{...item,candidate:false}:item)});
    setPreviewVersion(undefined);
  };
  const selectHistory = (index:number) => {if(imageHistory[index]) {setPreviewVersion(imageHistory[index].version_id);setShowHistory(true);}};
  const visibleVersion=previewVersion && imageHistory.some(item=>item.version_id===previewVersion) ? previewVersion:data.asset_version_id;
  const mediaRevisions = useContext(MediaRevisions);
  const mediaRevision = data.asset_version_id
    ? mediaRevisions[data.asset_version_id] || 0
    : 0;
  const [failed, setFailed] = useState(false);
  const imageVariant = data.kind === "audio" ? "waveform" : data.kind === "image" && (needsOriginal || props.selected) ? "original" : "thumbnail";
  useEffect(() => setFailed(false), [visibleVersion, mediaRevision, imageVariant]);
  const Icon =
    data.kind === "video" ? Video : data.kind === "audio" ? Music2 : ImageIcon;
  return (
    <NodeChrome {...props} className="media-node">
      <div className="media-node-heading">
        <NodeHeading id={props.id} data={data} icon={<Icon size={14} />} />
        {data.note && <p className="media-node-note">{data.note}</p>}
      </div>
      <div
        className={`media-node-poster ${data.kind === "audio" ? "audio-poster" : ""} ${!data.asset_version_id && data.generation ? "generation-draft-poster" : ""}`}
        onDoubleClick={event=>{if((["image","video","audio"].includes(data.kind||"")) && visibleVersion){event.stopPropagation();setPlaying(false);setLargePreview(visibleVersion);}}}
      >
        {data.kind==="image" && visibleVersion && <button className="media-open-image nodrag nopan" title="查看原图" onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();setLargePreview(visibleVersion);}}>查看大图</button>}
        {data.kind==="audio" && playing && visibleVersion ? <audio className="inline-audio nodrag nopan nowheel" src={mediaUrl(visibleVersion,"original")} autoPlay controls preload="metadata" onPointerDown={e=>e.stopPropagation()}/> : data.kind==="video" && playing && visibleVersion ? <video key={visibleVersion} className="inline-video nodrag nopan nowheel" src={mediaUrl(visibleVersion,"original")} poster={mediaUrl(visibleVersion)} autoPlay controls playsInline preload="metadata" onPointerDown={e=>e.stopPropagation()}/> : data.asset_version_id && !failed ? (
          <img
            src={`${mediaUrl(visibleVersion || data.asset_version_id, imageVariant)}&refresh=${mediaRevision}`}
            loading="lazy"
            decoding="async"
            className={
              data.kind === "audio" ? "audio-waveform-image" : undefined
            }
            alt={data.title || "媒体素材"}
            draggable={false}
            onError={() => setFailed(true)}
          />
        ) : !data.asset_version_id && data.generation ? (
          <div className="generation-draft-art">
            <Sparkles size={31} strokeWidth={1.3} />
            <span>{data.kind==="audio"?"输入台词，用人物的声音讲述故事":data.kind==="video"?"描述动作与声音，让画面动起来":"描述画面，生成你的下一张图片"}</span>
          </div>
        ) : (
          <div className="media-node-unavailable">
            <Icon size={28} />
            <span>{failed ? "预览暂不可用" : "媒体素材"}</span>
          </div>
        )}
        {data.kind !== "image" && (
          <span className="media-kind">
            <Icon size={12} />
            {data.kind === "video"
              ? "视频"
              : data.kind === "audio"
                ? "音频"
                : "图片"}
          </span>
        )}
        {(data.kind === "video" || data.kind === "audio") && visibleVersion && !playing && <button className="poster-play nodrag nopan" title={data.kind==="audio"?"试听配音":"播放视频"} onPointerDown={e=>e.stopPropagation()} onClick={e=>{e.stopPropagation();setPlaying(true);}}>▶</button>}
        {data.kind === "video" && visibleVersion && <button className="media-open-image nodrag nopan" title="查看完整视频" onClick={e=>{e.stopPropagation();setPlaying(false);setLargePreview(visibleVersion);}}>查看视频</button>}
        <GenerationProgress job={generationJob} pending={!!data.generation?.pending_submission}/>
        {props.selected && data.kind === "image" && imageHistory.length > 1 && (
          <div
            className="media-history-controls nodrag nopan nowheel"
            onPointerDown={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            <button
              title="上一张历史图片"
              disabled={!!data.locked || currentHistoryIndex <= 0}
              onClick={() => selectHistory(currentHistoryIndex - 1)}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              className="media-history-count"
              title="查看图片历史"
              aria-expanded={showHistory}
              onClick={() => setShowHistory((value) => !value)}
            >
              {Math.max(0, currentHistoryIndex) + 1} / {imageHistory.length}
              <ChevronDown size={11} />
            </button>
            <button
              title="下一张历史图片"
              disabled={
                !!data.locked || currentHistoryIndex >= imageHistory.length - 1
              }
              onClick={() => selectHistory(currentHistoryIndex + 1)}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>
      {props.selected && data.kind==="image" && (showHistory || imageHistory.some(item=>item.candidate)) && <CandidateReview current={data.asset_version_id} preview={visibleVersion} history={imageHistory} locked={data.locked}
        onPreview={setPreviewVersion} onAdopt={adopt} onOpenImage={setLargePreview}
        onContinue={id=>{if(data.locked)return;actions.beginEdit();actions.updateData(props.id,{generation:{...defaultGenerationDraft(true),...data.generation,mode:"edit",workflow_id:undefined,edit_base_version_id:id}});setShowHistory(false);setPreviewVersion(undefined);}}
        onDiscard={id=>{if(data.locked)return;actions.beginEdit();actions.updateData(props.id,{image_history:imageHistory.filter(item=>item.version_id!==id)});setPreviewVersion(undefined);}}
      />}
      {props.selected && (data.kind==="video" || data.kind==="audio") && imageHistory.length>1 && <div className="video-history nodrag nopan nowheel" onPointerDown={e=>e.stopPropagation()}>{imageHistory.map((item,index)=><div key={item.version_id}><button className={item.version_id===data.asset_version_id?"adopted":""} title={`预览${data.kind==="audio"?"配音":"视频"}版本 ${index+1}`} onClick={()=>{setPlaying(false);setLargePreview(item.version_id);}}><img src={mediaUrl(item.version_id,data.kind==="audio"?"waveform":"thumbnail")} alt={`媒体版本 ${index+1}`}/><span>{item.version_id===data.asset_version_id?"当前版本":item.candidate?"候选版本":"历史版本"}</span></button>{item.version_id!==data.asset_version_id&&<><button disabled={data.locked} onClick={()=>adopt(item.version_id)}>采用此版</button><button disabled={data.locked} onClick={()=>{actions.beginEdit();actions.updateData(props.id,{image_history:imageHistory.filter(entry=>entry.version_id!==item.version_id)});}}>移出候选</button></>}</div>)}</div>}
      {largePreview && ((data.kind==="video"||data.kind==="audio")?<VideoViewer kind={data.kind} versionId={largePreview} versions={imageHistory.map(item=>item.version_id)} onClose={()=>setLargePreview(undefined)} />:<ImageViewer versionId={largePreview} versions={imageHistory.map(item=>item.version_id)} onClose={()=>setLargePreview(undefined)} />)}
    </NodeChrome>
  );
});

const TextNode = memo(function TextNode(props: NodeProps<CanvasNode>) {
  const actions = useContext(Actions)!;
  return (
    <NodeChrome {...props} className="text-node">
      <div className="text-node-label">
        <Type size={13} />
        <span>{props.data.title || "文字备注"}</span>
      </div>
      <textarea
        className="nodrag nowheel"
        value={props.data.text || ""}
        placeholder="写下灵感、分镜或对白…"
        readOnly={!!props.data.locked}
        onFocus={actions.beginEdit}
        onChange={(event) =>
          actions.updateData(props.id, { text: event.target.value })
        }
      />
    </NodeChrome>
  );
});

const SubjectNode = memo(function SubjectNode(props: NodeProps<CanvasNode>) {
  const actions = useContext(Actions)!;
  const subject = props.data.subject;
  if (!subject)
    return (
      <NodeChrome {...props} className="subject-node">
        主体资料暂不可用
      </NodeChrome>
    );
  const Icon = subjectKindIcons[subject.kind] || UserRound;
  return (
    <NodeChrome {...props} className="subject-node">
      <div className="media-node-heading">
        <NodeHeading
          id={props.id}
          data={props.data}
          icon={<Icon size={14} />}
          fallback={subjectKindNames[subject.kind] || "主体"}
        />
      </div>
      <SubjectNodeView
        subject={subject}
        subjectId={props.id}
        onBeforeVoiceDesign={actions.flushCanvas}
        onCreateVideo={()=>window.dispatchEvent(new CustomEvent("manju:create-native-video",{detail:{nodeId:props.id}}))}
        onCreateSpeech={()=>window.dispatchEvent(new CustomEvent("manju:create-speech",{detail:{nodeId:props.id}}))}
        displayWidth={props.width || 340}
        selected={props.selected}
        locked={!!props.data.locked}
        projectId={actions.projectId}
        getCanvasMedia={actions.getCanvasMedia}
        onChange={(snapshot: SubjectSnapshot) =>
          actions.updateSubject(props.id, snapshot)
        }
        onPreview={actions.preview}
      />
    </NodeChrome>
  );
});

const GroupNode = memo(function GroupNode(props: NodeProps<CanvasNode>) {
  const actions = useContext(Actions)!;
  return (
    <NodeChrome
      {...props}
      className={`group-node ${props.data.collapsed ? "is-collapsed" : ""}`}
    >
      <div className="group-node-heading">
        <button
          className="nodrag group-toggle"
          title={props.data.collapsed ? "展开分组" : "折叠分组"}
          onClick={() => actions.toggleGroup(props.id)}
        >
          {props.data.collapsed ? (
            <ChevronRight size={15} />
          ) : (
            <ChevronDown size={15} />
          )}
        </button>
        <Group size={14} />
        <span>{props.data.title || "分组"}</span>
      </div>
    </NodeChrome>
  );
});

const FrameNode = memo(function FrameNode(props: NodeProps<CanvasNode>) {
  const shot=props.data.shot as {title?:string;order?:number;scene?:string;dialogue?:string;speaker?:string;duration?:number;video_version_id?:string;audio_version_id?:string;status?:string}|undefined;
  return (
    <NodeChrome {...props} className={`frame-node ${shot?"production-shot-node":""}`}>
      <div className="frame-node-label">
        <Frame size={13} />
        <span>{props.data.title || "画框"}</span>
      </div>
      {shot&&<div className="production-shot-overview"><header><b>镜头 {shot.order||1}</b><span>{shot.duration||0} 秒 · {{draft:"草稿",ready:"待审核",approved:"已采用"}[shot.status||"draft"]||"草稿"}</span></header>{shot.video_version_id?<img src={mediaUrl(shot.video_version_id)} alt={shot.title||"镜头素材"} loading="lazy" draggable={false}/>:<div className="production-shot-placeholder"><Video size={25}/><span>尚未选择镜头素材</span></div>}<strong>{shot.title||props.data.title||"未命名镜头"}</strong><small>{shot.scene||"未设置场景"}{shot.audio_version_id?" · 已绑定配音":""}</small><p>{shot.speaker?shot.speaker+"：":""}{shot.dialogue||"未填写台词"}</p><small>双击打开分镜成片</small></div>}
    </NodeChrome>
  );
});

const nodeTypes = {
  media: MediaNode,
  subject: SubjectNode,
  text: TextNode,
  group: GroupNode,
  frame: FrameNode,
};

export default function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <CanvasEditor {...props} />
    </ReactFlowProvider>
  );
}

function CanvasEditor({
  project,
  onBack,
  onProjectChange,
  onPreview,
  assetsRefresh,
  onAssetsChange,
  onOpenComfy,
  onOpenTasks,
}: CanvasProps) {
  const flow = useReactFlow<CanvasNode>();
  const liveViewport = useViewport();
  const [editorSessionId] = useState(() => {
    try {
      const existing = sessionStorage.getItem("manju:canvas-editor-session");
      if (existing) return existing;
      const sessionId = uid();
      sessionStorage.setItem("manju:canvas-editor-session", sessionId);
      return sessionId;
    } catch {
      return uid();
    }
  });
  const [recoverableDraft, setRecoverableDraft] = useState<string | null>(null);
  const [nodes, setNodes] = useState<CanvasNode[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetPage, setAssetPage] = useState(0);
  const [assetTotal, setAssetTotal] = useState(0);
  const [mediaRevisions, setMediaRevisions] = useState<Record<string, number>>(
    {},
  );
  const [assetScope, setAssetScope] = useState<"project" | "all" | "subjects">(
    "project",
  );
  const [subjectRefresh, setSubjectRefresh] = useState(0);
  const [subjectDraft, setSubjectDraft] = useState<SubjectSnapshot | null>(
    null,
  );
  const [saveSelection, setSaveSelection] = useState<Snapshot | null>(null);
  const [contextMenu, setContextMenu] = useState<MenuState | null>(null);
  const [search, setSearch] = useState("");
  const [assetFilter, setAssetFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [assetLoading, setAssetLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [saveState, setSaveState] = useState<
    "saved" | "pending" | "saving" | "error" | "conflict"
  >("saved");
  const [changeSerial, setChangeSerial] = useState(0);
  const [historySerial, setHistorySerial] = useState(0);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [tool, setTool] = useState<"select" | "pan">("select");
  const [showFrames, setShowFrames] = useState(false);
  const [showSubjects, setShowSubjects] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const [showInspector, setShowInspector] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [showProduction, setShowProduction] = useState(false);
  const [showCanvasRun, setShowCanvasRun] = useState(false);
  const [showTimeline, setShowTimeline] = useState(false);
  const [showLipSync, setShowLipSync] = useState(false);
  const [lipSyncNodeId,setLipSyncNodeId] = useState<string>();
  const [showDrafts, setShowDrafts] = useState(false);
  const [showNavigator, setShowNavigator] = useState(false);
  const [nodeSearch, setNodeSearch] = useState("");
  const [renderingFrame, setRenderingFrame] = useState(false);
  const reconnectingEdge = useRef<Edge | null>(null);
  const [canvasPick,setCanvasPick]=useState<{kind:"image"|"audio";onChoose:(media:SubjectMediaCandidate)=>void}|null>(null);
  const [pickOptions,setPickOptions]=useState<SubjectMediaCandidate[]>([]);
  useEffect(()=>{
    const begin=(event:Event)=>{setCanvasPick((event as CustomEvent).detail);setPickOptions([]);};
    const cancel=(event:KeyboardEvent)=>{if(event.key==="Escape" && document.querySelector(".canvas-pick-banner")){event.stopImmediatePropagation();event.preventDefault();setCanvasPick(null);setPickOptions([]);}};
    window.addEventListener("manju:pick-canvas-media",begin);window.addEventListener("keydown",cancel,true);
    return()=>{window.removeEventListener("manju:pick-canvas-media",begin);window.removeEventListener("keydown",cancel,true);};
  },[]);
  const [connectionDrop, setConnectionDrop] = useState<{x:number;y:number;source:string} | null>(null);
  const [edgeMenu, setEdgeMenu] = useState<{x:number;y:number;id:string} | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [stageDimensions, setStageDimensions] = useState({
    width: 900,
    height: 700,
  });
  const [composerHeight, setComposerHeight] = useState(310);
  const [videoShelfHeight, setVideoShelfHeight] = useState(0);
  const [imageHeadingHeight, setImageHeadingHeight] = useState(24);
  const [imageToolsSize, setImageToolsSize] = useState({
    width: 440,
    height: 46,
  });
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [assetDisplayName, setAssetDisplayName] = useState("");
  const [renamingAsset, setRenamingAsset] = useState(false);
  const [removeAsset, setRemoveAsset] = useState<Asset | null>(null);
  const [removingAsset, setRemovingAsset] = useState(false);
  const [failedUploads, setFailedUploads] = useState<
    { file: File; position: { x: number; y: number } }[]
  >([]);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const viewportRef = useRef<Viewport>(initialViewport);
  const revisionRef = useRef(project.revision || 0);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);
  const pendingSaveRef = useRef<PendingSave | null>(null);
  const savedDocumentRef = useRef<CanvasDocument | null>(null);
  const generationSyncTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const generationUpdatedNodes = useRef(new Set<string>());
  const removingAssetRef = useRef(false);
  const conflictRef = useRef(false);
  const interactingRef = useRef(false);
  const activeProjectRef = useRef(project.id);
  const localVersionRef = useRef(0);
  const history = useRef<{ past: Snapshot[]; future: Snapshot[] }>({
    past: [],
    future: [],
  });
  const clipboard = useRef<Snapshot | null>(null);
  const ownRequests = useRef(new Set<string>());
  const loadSequence = useRef(0);
  const assetLoadSequence = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const importPosition = useRef<{ x: number; y: number } | undefined>(
    undefined,
  );
  const suppressSelectionPan = useRef<string | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const composerAnchor = useRef<HTMLDivElement>(null);
  const imageTools = useRef<HTMLDivElement>(null);
  const manualViewportSerial = useRef(0);
  const draftPrefix = `manju:canvas-draft:${project.id}`;
  const draftKey = `${draftPrefix}:${editorSessionId}`;
  const viewKey = `manju:canvas-view:${project.id}`;
  const closeContextMenu = useCallback(() => setContextMenu(null), []);
  useRightButtonPan(stage, flow.getViewport, flow.setViewport, () => {
    manualViewportSerial.current += 1;
    closeContextMenu();
    setEdgeMenu(null);
    setConnectionDrop(null);
  });
  const openFilePicker = useCallback(
    (
      position?: { x: number; y: number },
      accept = "image/*,video/*,audio/*",
    ) => {
      importPosition.current = position;
      if (fileInput.current) {
        fileInput.current.accept = accept;
        fileInput.current.click();
      }
    },
    [],
  );

  useEffect(() => {
    if (!stage.current) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry)
        setStageDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, []);

  const replace = useCallback(
    (nextNodes: CanvasNode[], nextEdges = edgesRef.current) => {
      nodesRef.current = nextNodes;
      edgesRef.current = nextEdges;
      setNodes(nextNodes);
      setEdges(nextEdges);
    },
    [],
  );

  const persistDraft = useCallback(() => {
    try {
      localStorage.setItem(
        draftKey,
        JSON.stringify({
          revision: revisionRef.current,
          nodes: cleanNodes(nodesRef.current),
          edges: edgesRef.current.map(
            ({ selected: _selected, ...edge }) => edge,
          ),
          viewport: viewportRef.current,
          pending_request: pendingSaveRef.current?.document,
          saved_at: Date.now(),
        }),
      );
    } catch {
      setNotice("浏览器草稿空间不足，请保持页面打开并完成保存。");
    }
  }, [draftKey]);

  const changed = useCallback(() => {
    dirtyRef.current = true;
    localVersionRef.current += 1;
    if (!conflictRef.current) setSaveState("pending");
    persistDraft();
    setChangeSerial((value) => value + 1);
  }, [persistDraft]);

  const remember = useCallback(() => {
    const snapshot = {
      nodes: clone(nodesRef.current),
      edges: clone(edgesRef.current),
    };
    history.current.past.push(snapshot);
    if (history.current.past.length > 80) history.current.past.shift();
    history.current.future = [];
    setHistorySerial((value) => value + 1);
  }, []);

  const edit = useCallback(
    (nextNodes: CanvasNode[], nextEdges = edgesRef.current) => {
      remember();
      replace(reconcileReferences(nextNodes, nextEdges), nextEdges);
      changed();
    },
    [remember, replace, changed],
  );

  const loadCanvas = useCallback(
    async (preserveDraft = true, replaceDraft = false) => {
      const projectId = project.id;
      const sequence = ++loadSequence.current;
      const localVersion = localVersionRef.current;
      setLoading(true);
      setLoadError("");
      try {
        const document = await api<CanvasDocument>(
          `/api/projects/${projectId}/canvas`,
        );
        if (
          activeProjectRef.current !== projectId ||
          sequence !== loadSequence.current
        )
          return;
        // A remote refresh must not replace edits made while its GET was pending.
        if (!preserveDraft && (savingRef.current || localVersionRef.current !== localVersion || (!replaceDraft && dirtyRef.current))) {
          if (document.revision > revisionRef.current) {
            conflictRef.current = true;
            persistDraft();
            setSaveState("conflict");
            setNotice("画布出现新的外部修改，当前草稿已保留。");
          }
          return;
        }
        if (!preserveDraft) pendingSaveRef.current = null;
        savedDocumentRef.current = clone(document);
        let restored = document;
        let hasDraft = false;
        let hasConflict = false;
        if (preserveDraft) {
          try {
            const raw = localStorage.getItem(draftKey);
            if (raw) {
              const draft = JSON.parse(raw) as CanvasDocument & {
                pending_request?: SaveRequest;
              };
              if (
                Array.isArray(draft.nodes) &&
                Array.isArray(draft.edges) &&
                draft.viewport
              ) {
                restored = draft;
                hasDraft = true;
                if (draft.pending_request?.request_id) {
                  const pending = draft.pending_request;
                  const sameContent =
                    JSON.stringify([
                      pending.nodes,
                      pending.edges,
                    ]) ===
                    JSON.stringify([draft.nodes, draft.edges]);
                  pendingSaveRef.current = {
                    document: pending,
                    localVersion: sameContent ? localVersionRef.current : -1,
                  };
                  ownRequests.current.add(pending.request_id);
                }
                hasConflict =
                  draft.revision !== document.revision &&
                  !pendingSaveRef.current;
                setNotice(
                  hasConflict
                    ? "本机草稿与服务端版本存在差异，草稿已保留。"
                    : "已恢复上次未完成保存的本机草稿。",
                );
              }
            } else {
              const otherDrafts: { key: string; savedAt: number }[] = [];
              for (let index = 0; index < localStorage.length; index += 1) {
                const key = localStorage.key(index);
                if (
                  !key ||
                  (key !== draftPrefix && !key.startsWith(`${draftPrefix}:`))
                )
                  continue;
                try {
                  const candidate = JSON.parse(
                    localStorage.getItem(key) || "null",
                  );
                  if (
                    candidate &&
                    Array.isArray(candidate.nodes) &&
                    Array.isArray(candidate.edges)
                  )
                    otherDrafts.push({
                      key,
                      savedAt: Number(candidate.saved_at) || 0,
                    });
                } catch {
                  /* Skip unreadable drafts from older sessions. */
                }
              }
              otherDrafts.sort(
                (first, second) => second.savedAt - first.savedAt,
              );
              setRecoverableDraft(otherDrafts[0]?.key || null);
            }
          } catch {
            setNotice("本机草稿读取失败，已加载服务端保存的画布。");
          }
        }
        // Older clients also wrote drafts for camera-only changes. If all content
        // already matches the server, there is no outstanding edit to recover.
        if (hasDraft &&
          JSON.stringify(cleanNodes(restored.nodes)) === JSON.stringify(cleanNodes(document.nodes)) &&
          JSON.stringify(restored.edges.map(({ selected: _selected, ...edge }) => edge)) ===
            JSON.stringify(document.edges.map(({ selected: _selected, ...edge }) => edge))) {
          restored = document;
          hasDraft = false;
          hasConflict = false;
          pendingSaveRef.current = null;
          try { localStorage.removeItem(draftKey); } catch { /* A matching draft is harmless if storage is unavailable. */ }
          setNotice("");
        }
        revisionRef.current =
          hasConflict || pendingSaveRef.current
            ? restored.revision
            : document.revision;
        let localView: Viewport | null = null;
        try {
          const value = JSON.parse(localStorage.getItem(viewKey) || "null");
          if (value && Number.isFinite(value.x) && Number.isFinite(value.y) && Number.isFinite(value.zoom) && value.zoom >= 0.12 && value.zoom <= 8)
            localView = value;
        } catch { /* The shared document remains usable without local view storage. */ }
        viewportRef.current = !preserveDraft ? flow.getViewport() : localView || restored.viewport || initialViewport;
        dirtyRef.current = hasDraft;
        conflictRef.current = hasConflict;
        history.current = { past: [], future: [] };
        replace(restored.nodes || [], restored.edges || []);
        setSaveState(hasConflict ? "conflict" : hasDraft ? "pending" : "saved");
        setZoom(viewportRef.current.zoom);
        setHistorySerial((value) => value + 1);
        setChangeSerial((value) => value + 1);
        requestAnimationFrame(() => flow.setViewport(viewportRef.current));
      } catch (error) {
        if (activeProjectRef.current === projectId)
          setLoadError(errorText(error));
      } finally {
        if (
          activeProjectRef.current === projectId &&
          sequence === loadSequence.current
        )
          setLoading(false);
      }
    },
    [project.id, draftKey, draftPrefix, viewKey, replace, flow, persistDraft],
  );

  useEffect(() => {
    activeProjectRef.current = project.id;
    dirtyRef.current = false;
    conflictRef.current = false;
    savingRef.current = false;
    pendingSaveRef.current = null;
    void loadCanvas();
    return () => {
      activeProjectRef.current = "";
    };
  }, [project.id, loadCanvas]);

  const reloadAssets = useCallback(async () => {
    if (assetScope === "subjects") return;
    const sequence = ++assetLoadSequence.current;
    setAssetLoading(true);
    try {
      const params = new URLSearchParams();
      if (assetScope === "project") params.set("project_id", project.id);
      if (search.trim()) params.set("search", search.trim());
      if (assetFilter) params.set("type", assetFilter);
      params.set("offset", String(assetPage * 60));
      const result = await api<{ items: Asset[]; total: number }>(
        `/api/assets?${params}`,
      );
      if (
        activeProjectRef.current === project.id &&
        sequence === assetLoadSequence.current
      ) {
        setAssets(result.items);
        setAssetTotal(result.total);
        if (!result.items.length && assetPage > 0)
          setAssetPage((value) => value - 1);
      }
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      if (sequence === assetLoadSequence.current) setAssetLoading(false);
    }
  }, [project.id, assetScope, search, assetFilter, assetPage]);

  useEffect(() => setAssetPage(0), [assetScope, search, assetFilter]);

  useEffect(() => {
    const timer = setTimeout(() => void reloadAssets(), 150);
    return () => clearTimeout(timer);
  }, [reloadAssets, assetsRefresh]);

  const save = useCallback(async () => {
    if (
      !dirtyRef.current ||
      savingRef.current ||
      conflictRef.current ||
      interactingRef.current ||
      loading
    )
      return;
    const projectId = project.id;
    const pending = pendingSaveRef.current || {
      localVersion: localVersionRef.current,
      document: {
        revision: revisionRef.current,
        nodes: cleanNodes(nodesRef.current),
        edges: edgesRef.current.map(({ selected: _selected, ...edge }) => edge),
        // Camera navigation is local; content saves retain the shared viewport.
        viewport: savedDocumentRef.current?.viewport || initialViewport,
        request_id: uid(),
      },
    };
    const { localVersion, document } = pending;
    const requestId = document.request_id;
    pendingSaveRef.current = pending;
    savingRef.current = true;
    ownRequests.current.add(requestId);
    persistDraft();
    setSaveState("saving");
    let savedSuccessfully = false;
    try {
      const saved = await api<CanvasDocument>(
        `/api/projects/${projectId}/canvas`,
        { method: "PUT", body: JSON.stringify(document) },
      );
      if (activeProjectRef.current !== projectId) return;
      pendingSaveRef.current = null;
      revisionRef.current = saved.revision;
      savedDocumentRef.current = clone(saved);
      savedSuccessfully = true;
      if (conflictRef.current) {
        persistDraft();
        setSaveState("conflict");
      } else if (localVersionRef.current === localVersion) {
        dirtyRef.current = false;
        localStorage.removeItem(draftKey);
        setSaveState("saved");
      } else {
        persistDraft();
        setSaveState("pending");
      }
    } catch (error) {
      if (activeProjectRef.current !== projectId) return;
      const status = (error as { status?: number }).status;
      const conflict =
        status === 409 ||
        /revision|conflict|409|版本冲突|修订/i.test(errorText(error));
      conflictRef.current = conflict;
      if (status && status < 500) pendingSaveRef.current = null;
      setSaveState(conflict ? "conflict" : "error");
      setNotice(
        conflict
          ? "画布已被其他窗口或 Agent 修改。当前编辑已保存在本机草稿。"
          : `保存失败，编辑已保留在本机。${errorText(error)}`,
      );
      persistDraft();
    } finally {
      savingRef.current = false;
      if (
        savedSuccessfully &&
        activeProjectRef.current === projectId &&
        dirtyRef.current &&
        !conflictRef.current &&
        localVersionRef.current !== localVersion
      )
        setChangeSerial((value) => value + 1);
      if (ownRequests.current.size > 200)
        ownRequests.current.delete(ownRequests.current.values().next().value!);
    }
  }, [draftKey, loading, persistDraft, project.id]);

  const flushCanvas = useCallback(async () => {
    const deadline = Date.now() + 15000;
    while (savingRef.current && Date.now() < deadline)
      await new Promise((resolve) => setTimeout(resolve, 50));
    if (conflictRef.current)
      throw new Error("请先处理画布版本冲突，再提交生成任务。");
    if (savingRef.current) throw new Error("画布仍在保存，请稍后重试提交。");
    if (dirtyRef.current) await save();
    if (dirtyRef.current || conflictRef.current)
      throw new Error("画布尚未保存成功，生成请求已保留，请恢复保存后重试。");
  }, [save]);

  const synchronizeGeneration: (updatedNodeIds?: string[]) => Promise<void> =
    useCallback(
      async (updatedNodeIds = []) => {
        updatedNodeIds.forEach((id) => generationUpdatedNodes.current.add(id));
        if (activeProjectRef.current !== project.id) return;
        if (savingRef.current) {
          clearTimeout(generationSyncTimer.current);
          generationSyncTimer.current = setTimeout(
            () => void synchronizeGeneration(),
            150,
          );
          return;
        }
        try {
          const remote = await api<CanvasDocument>(
            `/api/projects/${project.id}/canvas`,
          );
          if (
            activeProjectRef.current !== project.id ||
            remote.revision <= revisionRef.current
          )
            return;
          if (savingRef.current) {
            generationSyncTimer.current = setTimeout(
              () => void synchronizeGeneration(),
              150,
            );
            return;
          }
          const base = savedDocumentRef.current;
          const same = (first: unknown, second: unknown) =>
            JSON.stringify(first) === JSON.stringify(second);
          const withoutGeneratedImage = (node: CanvasNode) => {
            const copy = clone(node);
            delete copy.data.asset_version_id;
            delete copy.data.generation_id;
            delete copy.data.image_history;
            if (copy.data.kind === "image") delete copy.data.kind;
            return copy;
          };
          const resultUpdates = new Map<string, CanvasNode>();
          if (base)
            for (const node of base.nodes) {
              const next = remote.nodes.find((item) => item.id === node.id);
              if (
                next &&
                generationUpdatedNodes.current.has(node.id) &&
                next.data.asset_version_id &&
                next.data.image_history?.some(
                  (item) => item.version_id === next.data.asset_version_id,
                ) &&
                same(withoutGeneratedImage(node), withoutGeneratedImage(next))
              )
                resultUpdates.set(node.id, next);
            }
          const generationOnly =
            !!base &&
            base.revision === revisionRef.current &&
            base.nodes.every(
              (node) =>
                resultUpdates.has(node.id) ||
                same(
                  node,
                  remote.nodes.find((item) => item.id === node.id),
                ),
            ) &&
            base.edges.every((edge) =>
              same(
                edge,
                remote.edges.find((item) => item.id === edge.id),
              ),
            ) &&
            same(base.viewport, remote.viewport);
          if (!generationOnly) {
            if (dirtyRef.current || conflictRef.current) {
              conflictRef.current = true;
              persistDraft();
              setSaveState("conflict");
              setNotice(
                "生成结果已入库，同时检测到其他画布修改。当前草稿已保留，请处理版本冲突。",
              );
            } else await loadCanvas(false);
            return;
          }
          const newNodes = remote.nodes.filter(
            (node) => !base.nodes.some((item) => item.id === node.id),
          );
          const newEdges = remote.edges.filter(
            (edge) => !base.edges.some((item) => item.id === edge.id),
          );
          const append = (
            snapshot: Snapshot,
            preserveSelection = false,
          ): Snapshot => {
            const mergedNodes = [
              ...snapshot.nodes.map((node) => {
                const updated = resultUpdates.get(node.id);
                if (!updated) return node;
                const imageHistory = [...(node.data.image_history || [])];
                if (
                  node.data.asset_version_id &&
                  !imageHistory.some(
                    (item) => item.version_id === node.data.asset_version_id,
                  )
                )
                  imageHistory.push({
                    version_id: node.data.asset_version_id,
                    job_id: node.data.generation_id,
                  });
                for (const item of updated.data.image_history || []) {
                  const existing = imageHistory.findIndex(
                    (entry) => entry.version_id === item.version_id,
                  );
                  if (existing < 0) imageHistory.push(item);
                  else
                    imageHistory[existing] = {
                      ...imageHistory[existing],
                      ...item,
                    };
                }
                const baseVersion = base.nodes.find(
                  (item) => item.id === node.id,
                )?.data.asset_version_id;
                const selectedVersion =
                  node.data.asset_version_id &&
                  (preserveSelection ||
                    node.data.asset_version_id !== baseVersion)
                    ? node.data.asset_version_id
                    : updated.data.asset_version_id;
                return {
                  ...node,
                  data: {
                    ...node.data,
                    kind: updated.data.kind || node.data.kind,
                    asset_version_id: selectedVersion,
                    generation_id: imageHistory.find(
                      (item) => item.version_id === selectedVersion,
                    )?.job_id,
                    image_history: imageHistory,
                  },
                };
              }),
              ...newNodes.filter(
                (node) => !snapshot.nodes.some((item) => item.id === node.id),
              ),
            ];
            const ids = new Set(mergedNodes.map((node) => node.id));
            const mergedEdges = [
              ...snapshot.edges,
              ...newEdges.filter(
                (edge) =>
                  !snapshot.edges.some((item) => item.id === edge.id) &&
                  ids.has(edge.source) &&
                  ids.has(edge.target),
              ),
            ];
            return { nodes: mergedNodes, edges: mergedEdges };
          };
          const merged = append({
            nodes: nodesRef.current,
            edges: edgesRef.current,
          });
          history.current.past = history.current.past.map((snapshot) =>
            append(snapshot, true),
          );
          history.current.future = history.current.future.map((snapshot) =>
            append(snapshot, true),
          );
          revisionRef.current = remote.revision;
          savedDocumentRef.current = clone(remote);
          pendingSaveRef.current = null;
          generationUpdatedNodes.current.clear();
          conflictRef.current = false;
          replace(merged.nodes, merged.edges);
          if (dirtyRef.current) changed();
          else setSaveState("saved");
          setNotice("");
          void reloadAssets();
          onAssetsChange();
        } catch (error) {
          setNotice(errorText(error));
        }
      },
      [
        project.id,
        changed,
        loadCanvas,
        onAssetsChange,
        persistDraft,
        reloadAssets,
        replace,
      ],
    );

  useEffect(() => () => clearTimeout(generationSyncTimer.current), []);

  useEffect(() => {
    if (!loading) {
      const timer = setTimeout(() => void save(), 500);
      return () => clearTimeout(timer);
    }
  }, [changeSerial, loading, save]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      persistDraft();
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [persistDraft]);

  useEffect(() => {
    let disposed = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const reconcile = async () => {
      if (disposed || loading || removingAssetRef.current) return;
      if (savingRef.current) {
        retryTimer = setTimeout(() => void reconcile(), 250);
        return;
      }
      if (dirtyRef.current && pendingSaveRef.current && !conflictRef.current)
        await save();
      if (disposed || conflictRef.current) return;
      try {
        const latest = await api<CanvasDocument>(
          `/api/projects/${project.id}/canvas`,
        );
        if (disposed || activeProjectRef.current !== project.id) return;
        if (latest.revision > revisionRef.current) {
          if (dirtyRef.current || savingRef.current) {
            conflictRef.current = true;
            persistDraft();
            setSaveState("conflict");
            setNotice("连接已恢复，服务端有新的画布版本。当前草稿已保留。");
          } else await loadCanvas(false);
        }
        void reloadAssets();
      } catch (error) {
        if (!disposed) setNotice(errorText(error));
      }
    };
    const onReconnect = () => {
      setSubjectRefresh((value) => value + 1);
      void reconcile();
    };
    window.addEventListener("manju:reconnected", onReconnect);
    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      window.removeEventListener("manju:reconnected", onReconnect);
    };
  }, [loading, project.id, save, loadCanvas, persistDraft, reloadAssets]);

  useEffect(() => {
    const onEvent = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      const payload = detail.data || detail.payload || detail;
      const eventType = String(
        detail.type || detail.event || payload.type || "",
      );
      if (payload.request_id && ownRequests.current.has(payload.request_id))
        return;
      if (eventType.includes("asset")) void reloadAssets();
      if (eventType.startsWith("subject."))
        setSubjectRefresh((value) => value + 1);
      if (eventType === "asset.updated" && payload.version_id) {
        setMediaRevisions((current) => ({
          ...current,
          [payload.version_id]: (current[payload.version_id] || 0) + 1,
        }));
      }
      if (payload.project_id !== project.id || !eventType.includes("canvas"))
        return;
      if (
        removingAssetRef.current ||
        Number(payload.revision) <= revisionRef.current
      )
        return;
      if (payload.reason === "generation_result") {
        void synchronizeGeneration(
          Array.isArray(payload.updated_node_ids)
            ? payload.updated_node_ids
            : [],
        );
        return;
      }
      if (dirtyRef.current || savingRef.current) {
        conflictRef.current = true;
        setSaveState("conflict");
        persistDraft();
        setNotice("画布出现新的外部修改，当前草稿已保留。");
      } else void loadCanvas(false);
    };
    window.addEventListener("manju:event", onEvent);
    return () => window.removeEventListener("manju:event", onEvent);
  }, [
    loadCanvas,
    persistDraft,
    project.id,
    reloadAssets,
    synchronizeGeneration,
  ]);

  const undo = useCallback(() => {
    const snapshot = history.current.past.pop();
    if (!snapshot) return;
    history.current.future.push({
      nodes: clone(nodesRef.current),
      edges: clone(edgesRef.current),
    });
    replace(snapshot.nodes, snapshot.edges);
    changed();
    setHistorySerial((value) => value + 1);
  }, [changed, replace]);

  const redo = useCallback(() => {
    const snapshot = history.current.future.pop();
    if (!snapshot) return;
    history.current.past.push({
      nodes: clone(nodesRef.current),
      edges: clone(edgesRef.current),
    });
    replace(snapshot.nodes, snapshot.edges);
    changed();
    setHistorySerial((value) => value + 1);
  }, [changed, replace]);

  const updateData = useCallback(
    (id: string, patch: Partial<CanvasData>) => {
      const current = nodesRef.current.find(node => node.id === id);
      if (!current || Object.entries(patch).every(([key, value]) => JSON.stringify(current.data[key]) === JSON.stringify(value))) return;
      replace(
        nodesRef.current.map((node) =>
          node.id === id ? { ...node, data: { ...node.data, ...patch } } : node,
        ),
      );
      changed();
    },
    [replace, changed],
  );

  const centerPosition = useCallback(() => {
    const rect = stage.current?.getBoundingClientRect();
    return flow.screenToFlowPosition({
      x: rect ? rect.left + rect.width / 2 - 130 : 400,
      y: rect ? rect.top + rect.height / 2 - 90 : 300,
    });
  }, [flow]);

  const addMedia = useCallback(
    async (asset: Asset, position = centerPosition()) => {
      const projectId = project.id;
      try {
        await api(`/api/projects/${projectId}/assets`, {
          method: "POST",
          body: JSON.stringify({ asset_id: asset.id }),
        });
        if (activeProjectRef.current !== projectId) return;
        const node: CanvasNode = {
          id: uid(),
          type: "media",
          position,
          style: { width: 264, height: asset.type === "audio" ? 184 : 214 },
          data: {
            asset_version_id: asset.current_version_id,
            title: asset.name,
            kind: asset.type,
          },
          selected: true,
        };
        edit([
          ...nodesRef.current.map((item) => ({ ...item, selected: false })),
          node,
        ]);
        void reloadAssets();
        onAssetsChange();
      } catch (error) {
        if (activeProjectRef.current === projectId) setNotice(errorText(error));
      }
    },
    [centerPosition, edit, onAssetsChange, project.id, reloadAssets],
  );

  const importFiles = useCallback(
    async (files: File[], position = centerPosition()) => {
      if (!files.length) return;
      const projectId = project.id;
      setUploadProgress(0);
      const imported: CanvasNode[] = [];
      const errors: string[] = [];
      const failed: { file: File; position: { x: number; y: number } }[] = [];
      for (let index = 0; index < files.length; index += 1) {
        try {
          const asset = await uploadAsset(files[index], {
            projectId,
            onProgress: (progress) =>
              setUploadProgress(
                Math.round(((index + progress / 100) / files.length) * 100),
              ),
          });
          imported.push({
            id: uid(),
            type: "media",
            position: {
              x: position.x + (index % 3) * 290,
              y: position.y + Math.floor(index / 3) * 240,
            },
            style: { width: 264, height: asset.type === "audio" ? 184 : 214 },
            data: {
              asset_version_id:
                asset.imported_version_id || asset.current_version_id,
              title: asset.name,
              kind: asset.type,
            },
            selected: true,
          });
        } catch (error) {
          errors.push(`${files[index].name}：${errorText(error)}`);
          failed.push({
            file: files[index],
            position: {
              x: position.x + (index % 3) * 290,
              y: position.y + Math.floor(index / 3) * 240,
            },
          });
        }
      }
      if (activeProjectRef.current === projectId) {
        if (imported.length)
          edit([
            ...nodesRef.current.map((item) => ({ ...item, selected: false })),
            ...imported,
          ]);
        setUploadProgress(null);
        if (errors.length) setNotice(errors.join("；"));
        if (failed.length)
          setFailedUploads((current) => [...current, ...failed]);
        void reloadAssets();
        onAssetsChange();
      }
    },
    [centerPosition, edit, onAssetsChange, project.id, reloadAssets],
  );

  const addSubject = useCallback(
    async (subject: Subject, position = centerPosition()) => {
      const projectId = project.id;
      try {
        if (subject.asset_id)
          await api(`/api/projects/${projectId}/assets`, {
            method: "POST",
            body: JSON.stringify({ asset_id: subject.asset_id }),
          });
        if (activeProjectRef.current !== projectId) return;
        const snapshot = subjectSnapshot(subject);
        edit([
          ...nodesRef.current.map((node) => ({ ...node, selected: false })),
          {
            id: uid(),
            type: "subject",
            position,
            style: { width: 360, height: 400 },
            data: {
              kind: "image",
              title: subject.name,
              subject: snapshot,
              asset_version_id: snapshot.image_version_ids[0],
            },
            selected: true,
          },
        ]);
        onAssetsChange();
      } catch (error) {
        if (activeProjectRef.current === projectId) setNotice(errorText(error));
      }
    },
    [centerPosition, edit, onAssetsChange, project.id],
  );

  const addEmptySubject = useCallback(
    (kind: SubjectKind, position = centerPosition()) => {
      const name = subjectKindNames[kind];
      edit([
        ...nodesRef.current.map((node) => ({ ...node, selected: false })),
        {
          id: uid(),
          type: "subject",
          position,
          style: { width: 360, height: 400 },
          data: {
            title: name,
            kind: "image",
            subject: { kind, name, description: "", image_version_ids: [] },
          },
          selected: true,
        },
      ]);
      setShowSubjects(false);
    },
    [centerPosition, edit],
  );

  const convertToSubject = useCallback(
    (id: string, kind: SubjectKind) => {
      edit(
        nodesRef.current.map((node) => {
          if (
            node.id !== id ||
            node.type !== "media" ||
            node.data.kind !== "image" ||
            node.data.locked
          )
            return node;
          const {
            generation: _generation,
            generation_id: _generationId,
            ...data
          } = node.data;
          const size = dimensions(node);
          const width = Math.max(360, size.width);
          const height = Math.max(400, size.height);
          return {
            ...node,
            type: "subject",
            width,
            height,
            style: { ...node.style, width, height },
            data: {
              ...data,
              kind: "image",
              subject: {
                kind,
                name: data.title || subjectKindNames[kind],
                description: data.note || "",
                image_version_ids: data.asset_version_id
                  ? [data.asset_version_id]
                  : [],
              },
            },
          };
        }),
      );
    },
    [edit],
  );

  const addText = useCallback(
    (position = centerPosition(), text = "") => {
      edit([
        ...nodesRef.current.map((node) => ({ ...node, selected: false })),
        {
          id: uid(),
          type: "text",
          position,
          style: { width: 260, height: 190 },
          data: { title: "文字备注", text },
          selected: true,
        },
      ]);
    },
    [centerPosition, edit],
  );

  const addGeneration = useCallback(
    (targetPosition?: { x: number; y: number }) => {
      const bounds = stage.current?.getBoundingClientRect();
      const position =
        targetPosition ||
        (bounds
          ? flow.screenToFlowPosition({
              x: bounds.left + bounds.width / 2 - 180,
              y: bounds.top + 108,
            })
          : centerPosition());
      edit([
        ...nodesRef.current.map((node) => ({ ...node, selected: false })),
        {
          id: uid(),
          type: "media",
          position,
          style: { width: 360, height: 240 },
          data: {
            title: "图片创作",
            kind: "image",
            generation: defaultGenerationDraft(),
          },
          selected: true,
        },
      ]);
    },
    [centerPosition, edit, flow],
  );

  const addVideoGeneration = async (targetPosition?: {x:number;y:number}, sourceId?:string) => {
    const source=nodesRef.current.find(node=>node.id===sourceId);
    const bounds=stage.current?.getBoundingClientRect();
    const position=targetPosition || (bounds?flow.screenToFlowPosition({x:bounds.left+bounds.width/2-190,y:bounds.top+110}):centerPosition());
    const id=uid();
    const projectId=project.id;
    let profile: import("./videoProfile").VideoProfile;
    try { profile=await api<import("./videoProfile").VideoProfile>("/api/video/settings"); }
    catch(error){setNotice("无法读取视频工作流默认配置："+errorText(error));return;}
    if(activeProjectRef.current!==projectId)return;
    if(source&&!nodesRef.current.some(node=>node.id===source.id))return;
    const draft=defaultVideoDraft(profile.defaults);
    if(source?.data.asset_version_id)draft.video_mode="frames";
    const character=source?.data.subject;
    if(character){
      draft.audio=true;
      draft.references=character.image_version_ids.slice(0,1).map(version_id=>({id:uid(),version_id,node_id:source!.id,title:character.name,description:character.description,use_description:true,source:"mention",media_type:"image",role:"reference",purpose:"identity"}));
      if(character.voice_version_id)draft.references.push({id:uid(),version_id:character.voice_version_id,node_id:source!.id,title:character.voice_name||character.name+" · 音色",source:"mention",media_type:"audio",role:"reference",purpose:"voice"});
      draft.video_mode=draft.references.length?"reference":"text";
    }
    const card:CanvasNode={id,type:"media",position,style:{width:380,height:240},data:{title:"视频创作",kind:"video",generation:draft},selected:true};
    edit([...nodesRef.current.map(node=>({...node,selected:false})),card],source?.data.asset_version_id&&!character?[...edgesRef.current,{id:uid(),source:source.id,target:id,type:"default",data:{role:"reference"}}]:edgesRef.current);
  };
  useEffect(()=>{const handler=(event:Event)=>{void addVideoGeneration(undefined,(event as CustomEvent<{nodeId:string}>).detail.nodeId);};window.addEventListener("manju:create-native-video",handler);return()=>window.removeEventListener("manju:create-native-video",handler);});

  const addSpeechGeneration = async (targetPosition?:{x:number;y:number}, sourceId?:string) => {
    const source=nodesRef.current.find(n=>n.id===sourceId),id=uid(),projectId=project.id;
    const position=targetPosition || (source?{x:absolutePosition(source,nodesRef.current).x+dimensions(source).width+100,y:absolutePosition(source,nodesRef.current).y}:centerPosition());
    let profile:import("./AudioWorkflow").AudioProfile;
    try{profile=await api<import("./AudioWorkflow").AudioProfile>("/api/audio/settings");}catch(error){setNotice(errorText(error));return;}
    if(activeProjectRef.current!==projectId || source&&!nodesRef.current.some(n=>n.id===source.id))return;
    const draft=defaultSpeechDraft(profile);
    const card:CanvasNode={id,type:"media",position,style:{width:380,height:200},data:{title:source?.data.subject?source.data.subject.name+" · 配音":"人物配音",kind:"audio",generation:draft},selected:true};
    edit([...nodesRef.current.map(n=>({...n,selected:false})),card],source?[...edgesRef.current,{id:uid(),source:source.id,target:id,type:"default",data:{role:"reference"}}]:edgesRef.current);
  };
  useEffect(()=>{const handler=(event:Event)=>{void addSpeechGeneration(undefined,(event as CustomEvent<{nodeId:string}>).detail.nodeId);};window.addEventListener("manju:create-speech",handler);return()=>window.removeEventListener("manju:create-speech",handler);});

  const addFrame = (aspect: "16:9" | "9:16", position = centerPosition()) => {
    edit([
      ...nodesRef.current.map((node) => ({ ...node, selected: false })),
      {
        id: uid(),
        type: "frame",
        position,
        style: {
          width: aspect === "16:9" ? 640 : 360,
          height: aspect === "16:9" ? 360 : 640,
        },
        zIndex: -10,
        data: { title: `画框 ${aspect}` },
        selected: true,
      },
    ]);
    setShowFrames(false);
  };

  const deleteSelection = useCallback(() => {
    const deleting = new Set(
      nodesRef.current
        .filter((node) => node.selected && !node.data.locked && !edgesRef.current.some(edge=>(edge.source===node.id || edge.target===node.id) && edgeLocked(edge,nodesRef.current)))
        .map((node) => node.id),
    );
    const selectedEdges = edgesRef.current.some((edge) => edge.selected);
    if (!deleting.size && !selectedEdges) return;
    const nextNodes = nodesRef.current
      .filter((node) => !deleting.has(node.id))
      .map((node) => {
        if (!node.parentId || !deleting.has(node.parentId)) return node;
        return {
          ...node,
          position: absolutePosition(node, nodesRef.current),
          parentId: undefined,
          extent: undefined,
          expandParent: undefined,
        };
      });
    edit(
      nextNodes,
      edgesRef.current.filter(
        (edge) =>
          (!edge.selected || edgeLocked(edge,nodesRef.current)) &&
          !deleting.has(edge.source) &&
          !deleting.has(edge.target),
      ),
    );
  }, [edit]);

  const getSelectionSnapshot = useCallback((): Snapshot | null => {
    const selection = nodesRef.current.filter((node) => node.selected);
    if (!selection.length) return null;
    const selectedIds = new Set(selection.map((node) => node.id));
    const copied = nodesRef.current.filter(
      (node) =>
        selectedIds.has(node.id) ||
        selection.some((parent) =>
          isDescendant(node, parent.id, nodesRef.current),
        ),
    );
    const ids = new Set(copied.map((node) => node.id));
    return {
      nodes: clone(
        copied.map((node) =>
          node.parentId && !ids.has(node.parentId)
            ? {
                ...node,
                position: absolutePosition(node, nodesRef.current),
                parentId: undefined,
                extent: undefined,
              }
            : node,
        ),
      ),
      edges: clone(
        edgesRef.current.filter(
          (edge) => ids.has(edge.source) && ids.has(edge.target),
        ),
      ),
    };
  }, []);

  const copySelection = useCallback(() => {
    const snapshot = getSelectionSnapshot();
    if (!snapshot) return;
    clipboard.current = snapshot;
    void navigator.clipboard
      ?.writeText(JSON.stringify({ manju_canvas: 1, ...clipboard.current }))
      .catch(() => {});
  }, [getSelectionSnapshot]);

  const pasteSnapshot = useCallback(
    (snapshot: Snapshot, targetPosition?: { x: number; y: number }) => {
      if (!snapshot.nodes.length) return;
      const ids = new Map(snapshot.nodes.map((node) => [node.id, uid()]));
      const roots = snapshot.nodes.filter(
        (node) => !node.parentId || !ids.has(node.parentId),
      );
      const origin = {
        x: Math.min(...roots.map((node) => node.position.x)),
        y: Math.min(...roots.map((node) => node.position.y)),
      };
      const copiedEdges = snapshot.edges.filter(
        (edge) => ids.has(edge.source) && ids.has(edge.target),
      );
      const edgeIds = new Map(copiedEdges.map((edge) => [edge.id, uid()]));
      const nextNodes = snapshot.nodes.map((node) => {
        const copied = clone(node);
        // A copied card keeps its creative draft, never another card's live job.
        delete copied.data.generation_id;
        copied.data.image_history?.forEach((item) => {
          delete item.job_id;
        });
        const draft = copied.data.generation;
        if (draft) {
          delete draft.last_job_id;
          delete draft.pending_submission;
          delete draft.pending_request_id;
          if(draft.subject_node_id)draft.subject_node_id=ids.get(draft.subject_node_id) || (nodesRef.current.some(item=>item.id===draft.subject_node_id)?draft.subject_node_id:undefined);
          draft.references = (draft.references || []).map((reference) => ({
            ...reference,
            node_id: reference.node_id
              ? ids.get(reference.node_id) ||
                (nodesRef.current.some((item) => item.id === reference.node_id)
                  ? reference.node_id
                  : undefined)
              : undefined,
            edge_id: reference.edge_id
              ? edgeIds.get(reference.edge_id)
              : undefined,
            source:
              reference.source === "connection" &&
              (!reference.edge_id || !edgeIds.has(reference.edge_id))
                ? "mention"
                : reference.source,
          }));
          if (draft.excluded_edge_ids)
            draft.excluded_edge_ids = draft.excluded_edge_ids.flatMap((id) => {
              const mapped = edgeIds.get(id);
              return mapped ? [mapped] : [];
            });
        }
        return {
          ...copied,
          id: ids.get(node.id)!,
          selected: true,
          parentId: node.parentId ? ids.get(node.parentId) : undefined,
          position:
            node.parentId && ids.has(node.parentId)
              ? node.position
              : targetPosition
                ? {
                    x: targetPosition.x + node.position.x - origin.x,
                    y: targetPosition.y + node.position.y - origin.y,
                  }
                : { x: node.position.x + 40, y: node.position.y + 40 },
        };
      });
      const nextEdges = copiedEdges.map((edge) => ({
        ...clone(edge),
        id: edgeIds.get(edge.id)!,
        source: ids.get(edge.source)!,
        target: ids.get(edge.target)!,
        selected: false,
      }));
      edit(
        [
          ...nodesRef.current.map((node) => ({ ...node, selected: false })),
          ...nextNodes,
        ],
        [...edgesRef.current, ...nextEdges],
      );
      clipboard.current = { nodes: clone(nextNodes), edges: clone(nextEdges) };
    },
    [edit],
  );

  const pasteAtPosition = useCallback(
    async (position: { x: number; y: number }) => {
      const projectId = project.id;
      const { payload, error } = await readCanvasClipboard(clipboard.current);
      if (activeProjectRef.current !== projectId) return;
      if (!payload) {
        setNotice(
          error
            ? "浏览器未允许直接读取剪贴板，请在画布按 Ctrl+V 粘贴。"
            : "剪贴板为空，请先复制卡片、图片或文字。",
        );
        return;
      }
      if (payload.kind === "canvas") pasteSnapshot(payload.snapshot, position);
      else if (payload.kind === "files")
        await importFiles(payload.files, position);
      else addText(position, payload.text);
    },
    [project.id, pasteSnapshot, importFiles, addText],
  );

  const groupSelection = useCallback(() => {
    const selected = nodesRef.current.filter(
      (node) => node.selected && !node.data.locked,
    );
    const roots = selected.filter(
      (node) =>
        !selected.some((parent) =>
          isDescendant(node, parent.id, nodesRef.current),
        ),
    );
    if (!roots.length) return;
    const positions = roots.map((node) => ({
      node,
      position: absolutePosition(node, nodesRef.current),
      size: dimensions(node),
    }));
    const left = Math.min(...positions.map((item) => item.position.x)) - 28;
    const top = Math.min(...positions.map((item) => item.position.y)) - 54;
    const right =
      Math.max(...positions.map((item) => item.position.x + item.size.width)) +
      28;
    const bottom =
      Math.max(...positions.map((item) => item.position.y + item.size.height)) +
      28;
    const id = uid();
    const group: CanvasNode = {
      id,
      type: "group",
      position: { x: left, y: top },
      style: { width: right - left, height: bottom - top },
      data: { title: "新建分组", collapsed: false },
      selected: true,
      zIndex: -5,
    };
    const rootIds = new Set(roots.map((node) => node.id));
    const nextNodes = nodesRef.current.map((node) => {
      if (!rootIds.has(node.id)) return { ...node, selected: false };
      const position = absolutePosition(node, nodesRef.current);
      return {
        ...node,
        parentId: id,
        position: { x: position.x - left, y: position.y - top },
        selected: false,
      };
    });
    edit([group, ...nextNodes]);
  }, [edit]);

  const ungroupSelection = useCallback(() => {
    const groupIds = new Set(
      nodesRef.current
        .filter(
          (node) => node.selected && node.type === "group" && !node.data.locked,
        )
        .map((node) => node.id),
    );
    if (!groupIds.size) return;
    const nextNodes = nodesRef.current
      .filter((node) => !groupIds.has(node.id))
      .map((node) => {
        if (!node.parentId || !groupIds.has(node.parentId)) return node;
        return {
          ...node,
          parentId: undefined,
          extent: undefined,
          position: absolutePosition(node, nodesRef.current),
          selected: true,
        };
      });
    edit(
      nextNodes,
      edgesRef.current.filter(
        (edge) => !groupIds.has(edge.source) && !groupIds.has(edge.target),
      ),
    );
  }, [edit]);

  const alignSelection = (mode: string) => {
    const selected = nodesRef.current.filter(
      (node) => node.selected && !node.data.locked,
    );
    const roots = selected.filter(
      (node) =>
        !selected.some((parent) =>
          isDescendant(node, parent.id, nodesRef.current),
        ),
    );
    if (roots.length < 2) return;
    const items = roots.map((node) => ({
      node,
      ...absolutePosition(node, nodesRef.current),
      ...dimensions(node),
    }));
    const minX = Math.min(...items.map((item) => item.x));
    const minY = Math.min(...items.map((item) => item.y));
    const maxX = Math.max(...items.map((item) => item.x + item.width));
    const maxY = Math.max(...items.map((item) => item.y + item.height));
    const next = new Map<string, { x: number; y: number }>();
    if (mode === "distribute-x" || mode === "distribute-y") {
      if (items.length < 3) return;
      const horizontal = mode === "distribute-x";
      items.sort((a, b) => (horizontal ? a.x - b.x : a.y - b.y));
      const span = horizontal ? maxX - minX : maxY - minY;
      const occupied = items.reduce(
        (sum, item) => sum + (horizontal ? item.width : item.height),
        0,
      );
      const gap = (span - occupied) / (items.length - 1);
      let cursor = horizontal ? minX : minY;
      items.forEach((item) => {
        next.set(item.node.id, {
          x: horizontal ? cursor : item.x,
          y: horizontal ? item.y : cursor,
        });
        cursor += (horizontal ? item.width : item.height) + gap;
      });
    } else {
      items.forEach((item) => {
        let { x, y } = item;
        if (mode === "left") x = minX;
        if (mode === "center-x") x = (minX + maxX - item.width) / 2;
        if (mode === "right") x = maxX - item.width;
        if (mode === "top") y = minY;
        if (mode === "center-y") y = (minY + maxY - item.height) / 2;
        if (mode === "bottom") y = maxY - item.height;
        next.set(item.node.id, { x, y });
      });
    }
    edit(
      nodesRef.current.map((node) => {
        const position = next.get(node.id);
        if (!position) return node;
        const parent = nodesRef.current.find(
          (item) => item.id === node.parentId,
        );
        const parentPosition = parent
          ? absolutePosition(parent, nodesRef.current)
          : { x: 0, y: 0 };
        return {
          ...node,
          position: {
            x: position.x - parentPosition.x,
            y: position.y - parentPosition.y,
          },
        };
      }),
    );
  };

  useEffect(() => {
    const typing = (target: EventTarget | null) =>
      target instanceof HTMLElement &&
      (!!target.closest(
        'input,textarea,select,[contenteditable="true"],.generation-composer',
      ) ||
        target.isContentEditable);
    const keydown = (event: KeyboardEvent) => {
      if (
        typing(event.target) ||
        event.isComposing ||
        loading ||
        document.querySelector('[aria-modal="true"]')
      )
        return;
      const modifier = event.ctrlKey || event.metaKey;
      if (modifier && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (modifier && event.key.toLowerCase() === "y") {
        event.preventDefault();
        redo();
      } else if (modifier && event.key.toLowerCase() === "a") {
        event.preventDefault();
        replace(nodesRef.current.map((node) => ({ ...node, selected: true })));
      } else if (modifier && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelection();
      } else if (modifier && event.key.toLowerCase() === "d") {
        event.preventDefault();
        copySelection();
        if (clipboard.current) pasteSnapshot(clipboard.current);
      } else if (modifier && event.key.toLowerCase() === "g") {
        event.preventDefault();
        if (event.shiftKey) ungroupSelection();
        else groupSelection();
      } else if (modifier && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelection();
      } else if (!modifier && event.key.toLowerCase() === "t") addText();
      else if (!modifier && event.key.toLowerCase() === "v") setTool("select");
      else if (event.key === "Escape")
        replace(
          nodesRef.current.map((node) => ({ ...node, selected: false })),
          edgesRef.current.map((edge) => ({ ...edge, selected: false })),
        );
    };
    const paste = (event: ClipboardEvent) => {
      if (
        typing(event.target) ||
        loading ||
        document.querySelector('[aria-modal="true"]')
      )
        return;
      const files = Array.from(event.clipboardData?.files || []);
      if (files.length) {
        event.preventDefault();
        void importFiles(files);
        return;
      }
      const raw = event.clipboardData?.getData("text/plain");
      if (raw) {
        const parsed = parseClipboardText(raw);
        if (parsed?.kind === "canvas") {
          event.preventDefault();
          pasteSnapshot(parsed.snapshot);
          return;
        }
        event.preventDefault();
        edit([
          ...nodesRef.current.map((node) => ({ ...node, selected: false })),
          {
            id: uid(),
            type: "text",
            position: centerPosition(),
            style: { width: 280, height: 200 },
            data: { title: "文字备注", text: raw },
            selected: true,
          },
        ]);
      } else if (clipboard.current) {
        event.preventDefault();
        pasteSnapshot(clipboard.current);
      }
    };
    window.addEventListener("keydown", keydown);
    window.addEventListener("paste", paste);
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("paste", paste);
    };
  }, [
    addText,
    centerPosition,
    copySelection,
    deleteSelection,
    edit,
    groupSelection,
    importFiles,
    loading,
    pasteSnapshot,
    redo,
    replace,
    save,
    undo,
    ungroupSelection,
  ]);

  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasNode>[]) => {
      const contentChanged = changes.some(change => {
        if (change.type !== "position" && change.type !== "dimensions") return false;
        const node = nodesRef.current.find(item => item.id === change.id);
        if (!node) return false;
        if (change.type === "position")
          return !!change.position && (change.position.x !== node.position.x || change.position.y !== node.position.y);
        return change.resizing === true && !!change.dimensions &&
          (change.dimensions.width !== dimensions(node).width || change.dimensions.height !== dimensions(node).height);
      });
      const next = applyNodeChanges(changes, nodesRef.current);
      replace(next);
      if (contentChanged) changed();
    },
    [changed, replace],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      replace(nodesRef.current, applyEdgeChanges(changes, edgesRef.current));
    },
    [replace],
  );
  const onConnect = useCallback(
    (connection: Connection) => {
      const source=nodesRef.current.find(node=>node.id===connection.source);
      const target=nodesRef.current.find(node=>node.id===connection.target);
      if (source?.data.locked || target?.data.locked || source?.id===target?.id) return;
      edit(
        nodesRef.current.map(node=>node.id===target?.id && target.data.kind==="video" && (!node.data.generation?.video_mode || node.data.generation.video_mode==="text") && canReference(source,target) ? {...node,data:{...node.data,generation:{...defaultVideoDraft(),...node.data.generation,video_mode:"reference"}}}:node),
        addEdge(
          {
            ...connection,
            id: uid(),
            type: "default",
            label: "",
            data: {role:canReference(source,target) ? "reference" : "relation"},
          },
          edgesRef.current,
        ),
      );
    },
    [edit],
  );
  const reconnectCanvasEdge = useCallback((edge:Edge, connection:Connection) => {
    const source=nodesRef.current.find(node=>node.id===connection.source),target=nodesRef.current.find(node=>node.id===connection.target);
    if (!source || !target || source.id===target.id || edgeLocked(edge,nodesRef.current) || source.data.locked || target.data.locked) return;
    if(edgeRole(edge)==="reference" && !canReference(source,target)){setNotice("参考线只能连接兼容的素材卡；文字说明请使用故事关系。");return;}
    const nextNodes=nodesRef.current.map(node=>{
      const generation=node.data.generation;
      const activateVideo=node.id===target.id && target.data.kind==="video" && edgeRole(edge)==="reference" && (!generation?.video_mode || generation.video_mode==="text");
      if(!generation && !activateVideo)return node;
      return {...node,data:{...node.data,generation:{...(activateVideo?defaultVideoDraft():{}),...generation,...(activateVideo?{video_mode:"reference" as const}:{}),references:(generation?.references||[]).filter(ref=>ref.source!=="connection" || ref.edge_id!==edge.id)}}} as CanvasNode;
    });
    edit(nextNodes,reconnectEdge(edgesRef.current.find(item=>item.id===edge.id)||edge,connection,edgesRef.current));
  },[edit]);
  const selected = nodes.filter((node) => node.selected);
  const single = selected.length === 1 ? selected[0] : null;
  const selectedEdge = edges.find((edge) => edge.selected);
  const selectedVersionId = single?.data.asset_version_id;
  const selectedImage =
    single?.type === "media" && single.data.kind === "image" ? single : null;
  const selectedSubject = single?.type === "subject" ? single : null;
  const selectedVideo=single?.type==="media" && single.data.kind==="video"?single:null;
  const selectedAudio=single?.type==="media" && single.data.kind==="audio"?single:null;
  const selectedPlayback=selectedVideo || selectedAudio;
  const composerNode = selectedImage || selectedPlayback;
  const videoReferences:ImageReference[]=nodes.filter(node=>node.id!==selectedVideo?.id).flatMap(node=>{
    const subject=node.data.subject;
    const result:ImageReference[]=[];
    if(subject){
      subject.image_version_ids.forEach((id,index)=>result.push({id:node.id+"-image-"+index,node_id:node.id,version_id:id,title:subject.name+(index?" · "+(index+1):""),description:subject.description,source:"mention",media_type:"image",purpose:"identity"}));
      if(subject.voice_version_id)result.push({id:node.id+"-voice",node_id:node.id,version_id:subject.voice_version_id,title:subject.name+" · 音色",source:"mention",media_type:"audio",purpose:"voice"});
    }else if(node.type==="media" && node.data.asset_version_id)result.push({id:node.id,node_id:node.id,version_id:node.data.asset_version_id,title:node.data.title||"参考素材",source:"mention",media_type:node.data.kind as "image"|"video"|"audio"});
    return result;
  });
  const imageEditingDisabled =
    !!selectedImage?.data.locked ||
    !!selectedImage?.data.generation?.pending_submission;
  const imagePosition = composerNode
    ? absolutePosition(composerNode, nodes)
    : { x: 0, y: 0 };
  const imageSize = composerNode
    ? dimensions(composerNode)
    : { width: 264, height: 214 };
  const imageScreen = {
    x: imagePosition.x * liveViewport.zoom + liveViewport.x,
    y: imagePosition.y * liveViewport.zoom + liveViewport.y,
  };
  const leftInset = stageDimensions.width > 620 ? 88 : 16;
  const rightInset = stageDimensions.width > 620 ? 24 : 16;
  const availableOverlayWidth = Math.max(
    1,
    stageDimensions.width - leftInset - rightInset,
  );
  let composerWidth = Math.min(760, availableOverlayWidth);
  let composerLeft = Math.max(
    leftInset,
    Math.min(
      stageDimensions.width - composerWidth - rightInset,
      imageScreen.x +
        (imageSize.width * liveViewport.zoom) / 2 -
        composerWidth / 2,
    ),
  );
  const imagePixelHeight = imageSize.height * liveViewport.zoom;
  const belowImage = imageScreen.y + imagePixelHeight + 22 + (selectedPlayback && videoShelfHeight ? (videoShelfHeight + 12) * liveViewport.zoom : 0);
  const belowSpace = stageDimensions.height - belowImage - 24;
  const aboveBottom =
    imageScreen.y - imageHeadingHeight - (selectedImage ? imageToolsSize.height : 0) - 36;
  const minimumComposerHeight = Math.min(
    selectedPlayback ? 180 : stageDimensions.width >= 1100 ? 310 : 220,
    Math.max(140, stageDimensions.height * 0.45),
  );
  let composerTop = belowImage;
  let composerMaxHeight = Math.max(1, belowSpace);
  if (belowSpace < minimumComposerHeight) {
    if (
      aboveBottom - 16 >= minimumComposerHeight &&
      imageScreen.y > stageDimensions.height / 2
    ) {
      composerMaxHeight = Math.min(composerHeight, aboveBottom - 16);
      composerTop = aboveBottom - composerMaxHeight;
    } else {
      const panelHeight = Math.min(
        composerHeight,
        Math.max(minimumComposerHeight, stageDimensions.height * 0.5),
      );
      const visibleImageBottom = Math.min(
        stageDimensions.height - minimumComposerHeight - 24,
        imageScreen.y +
          Math.min(
            imagePixelHeight,
            Math.max(80, stageDimensions.height * 0.25),
          ),
      );
      composerTop = Math.max(
        16,
        stageDimensions.height - panelHeight - 24,
        visibleImageBottom,
      );
      composerMaxHeight = Math.max(
        1,
        stageDimensions.height - composerTop - 24,
      );
    }
  }
  // Keep the zoom controls reachable when the panel uses the lower right corner.
  if (
    composerTop + Math.min(composerHeight, composerMaxHeight) >
      stageDimensions.height - 70 &&
    composerLeft + composerWidth > stageDimensions.width - 180
  ) {
    const widthBesideZoom = stageDimensions.width - leftInset - 180;
    if (widthBesideZoom >= 440) {
      composerWidth = Math.min(composerWidth, widthBesideZoom);
      composerLeft = Math.max(
        leftInset,
        Math.min(composerLeft, stageDimensions.width - composerWidth - 180),
      );
    } else {
      composerMaxHeight = Math.max(
        1,
        stageDimensions.height - composerTop - 72,
      );
    }
  }
  const imageToolsLeft = Math.max(
    leftInset,
    Math.min(
      stageDimensions.width - imageToolsSize.width - rightInset,
      imageScreen.x +
        (imageSize.width * liveViewport.zoom) / 2 -
        imageToolsSize.width / 2,
    ),
  );
  const imageToolsTop = Math.max(
    16,
    imageScreen.y - imageHeadingHeight - imageToolsSize.height - 24,
  );
  const imageVisible =
    imageScreen.x + imageSize.width * liveViewport.zoom >= 0 &&
    imageScreen.x <= stageDimensions.width &&
    imageScreen.y + imageSize.height * liveViewport.zoom >= 0 &&
    imageScreen.y <= stageDimensions.height;
  const generationConnections: ImageReference[] = (selectedImage?.data.generation?.references || []).filter(ref => ref.source === "connection");
  const unresolvedEdges = edges.filter(edge=>edge.target===selectedImage?.id && edgeRole(edge)==="pending");
  const changeEdgeRole = (id:string, role:string) => {
    const edge=edgesRef.current.find(item=>item.id===id);
    if (!edge || edgeLocked(edge,nodesRef.current)) return;
    if (role==="reference" && !canReference(nodesRef.current.find(node=>node.id===edge.source),nodesRef.current.find(node=>node.id===edge.target))) {setNotice("参考线需要有图片的来源和图片创作卡。");return;}
    edit(nodesRef.current,edgesRef.current.map(item=>item.id===id ? {...item,data:{...item.data,role}}:item));
  };
  const createFromConnection = (type:"media"|"text") => {
    if (!connectionDrop) return;
    const source=nodesRef.current.find(node=>node.id===connectionDrop.source);
    if (!source || source.data.locked) return;
    const id=uid();
    const node:CanvasNode={id,type,position:flow.screenToFlowPosition(connectionDrop),style:{width:360,height:type==="media"?240:190},selected:true,data:type==="media"?{title:"图片创作",kind:"image",generation:{...defaultGenerationDraft(),mode:"reference",use_current_image:false}}:{title:"关系备注",text:""}};
    edit([...nodesRef.current.map(node=>({...node,selected:false})),node],[...edgesRef.current,{id:uid(),source:source.id,target:id,sourceHandle:"out",targetHandle:"in",data:{role:canReference(source,node)?"reference":"relation"}}]);
    setConnectionDrop(null);
  };
  const canvasReferences: ImageReference[] = nodes.flatMap((node) => {
    if (node.id === selectedImage?.id) return [];
    if (node.type === "subject" && node.data.subject) {
      const subject = node.data.subject;
      return subject.image_version_ids.map((versionId, index) => ({
        version_id: versionId,
        node_id: node.id,
        title: index ? `${subject.name} · 参考${index + 1}` : subject.name,
        description:subject.description, use_description:true,
        source: "mention" as const,
      }));
    }
    return isImageReferenceNode(node) && node.data.asset_version_id
      ? [
          {
            version_id: node.data.asset_version_id,
            node_id: node.id,
            title: node.data.title || "画布图片",
            source: "mention" as const,
          },
        ]
      : [];
  });
  const displayedEdges = useMemo(() => {
    const images = new Set(
      nodes
        .filter((node) => node.type === "media" && (node.data.kind === "image" || node.data.kind === "video" || node.data.kind === "audio"))
        .map((node) => node.id),
    );
    const imageSources = new Set(
      nodes
        .filter(
          (node) => (isImageReferenceNode(node) || node.type==="media") && node.data.asset_version_id,
        )
        .map((node) => node.id),
    );
    const emphasizedNodes = new Set(
      nodes.filter((node) => node.selected).map((node) => node.id),
    );
    if (hoveredNodeId) emphasizedNodes.add(hoveredNodeId);
    return edges.map((edge) => {
      const reference =
        edgeRole(edge)==="reference" && imageSources.has(edge.source) && images.has(edge.target);
      const active =
        edge.selected ||
        emphasizedNodes.has(edge.source) ||
        emphasizedNodes.has(edge.target);
      return {
        ...edge,
        type: "default",
        reconnectable: !edgeLocked(edge,nodes),
        zIndex: edge.selected ? 1001 : 0,
        deletable: !edgeLocked(edge,nodes),
        label: edge.label || (edgeRole(edge)==="pending" ? "用途待确认" : reference ? (nodes.find(node=>node.id===edge.target)?.data.kind==="audio"?"音色参考":nodes.find(node=>node.id===edge.target)?.data.kind==="video"?"素材参考":"图片参考") : ""),
        className: `${edge.className || ""} canvas-connection-edge ${reference ? "canvas-reference-edge" : ""} ${active ? "is-active-connection" : ""}`,
        style: {
          ...edge.style,
          stroke: undefined,
          strokeWidth: undefined,
        },
        markerStart: undefined,
        markerEnd: undefined,
      };
    });
  }, [edges, nodes, hoveredNodeId]);

  useEffect(() => {
    const card = selectedPlayback && stage.current?.querySelector<HTMLElement>(`[data-id="${CSS.escape(selectedPlayback.id)}"]`);
    if (!card) {setVideoShelfHeight(0);return;}
    let shelf:HTMLElement|null=null;
    const measure = () => setVideoShelfHeight(shelf?.offsetHeight || 0);
    const observer = new ResizeObserver(measure);
    const update = () => {
      const next=card.querySelector<HTMLElement>(".video-history");
      if(next!==shelf){observer.disconnect();shelf=next;if(shelf)observer.observe(shelf);}
      measure();
    };
    // React Flow can render the node's selected controls after this effect runs.
    const children = new MutationObserver(update);
    children.observe(card,{childList:true,subtree:true});update();
    return () => {observer.disconnect();children.disconnect();};
  }, [selectedPlayback?.id, selectedPlayback?.data.image_history]);

  useEffect(() => {
    const element = composerAnchor.current;
    if (!element) return;
    const panel = element.firstElementChild as HTMLElement | null;
    if (!panel) return;
    const measure = () =>
      setComposerHeight(
        Math.ceil(
          Math.max(
            panel.getBoundingClientRect().height,
            panel.scrollHeight + 2,
          ),
        ),
      );
    const observer = new ResizeObserver(measure);
    const observe = () => {
      observer.disconnect();
      observer.observe(panel);
      for (const child of panel.children) observer.observe(child);
      measure();
    };
    observe();
    const children = new MutationObserver(observe);
    children.observe(panel, { childList: true });
    return () => {
      observer.disconnect();
      children.disconnect();
    };
  }, [composerNode?.id]);

  useEffect(() => {
    if (!composerNode) return;
    const heading = stage.current?.querySelector<HTMLElement>(
      `[data-id="${CSS.escape(composerNode.id)}"] .media-node-heading`,
    );
    const tools = imageTools.current;
    const measure = () => {
      if (heading)
        setImageHeadingHeight(heading.getBoundingClientRect().height);
      if (tools)
        setImageToolsSize({
          width: tools.offsetWidth,
          height: tools.offsetHeight,
        });
    };
    const observer = new ResizeObserver(measure);
    if (heading) observer.observe(heading);
    if (tools) observer.observe(tools);
    measure();
    return () => observer.disconnect();
  }, [
    composerNode?.id,
    composerNode?.data.asset_version_id,
    liveViewport.zoom,
  ]);

  useEffect(() => {
    if (!composerNode) return;
    const selectedId = composerNode.id;
    if (suppressSelectionPan.current === selectedId) return;
    const movement = manualViewportSerial.current;
    // Make room once on selection. Later status/parameter changes never pull the viewport.
    const timer = setTimeout(() => {
      if (
        suppressSelectionPan.current === selectedId ||
        interactingRef.current ||
        manualViewportSerial.current !== movement
      )
        return;
      const card = nodesRef.current.find(
        (node) => node.id === selectedId && node.selected,
      );
      const panel = composerAnchor.current;
      const bounds = stage.current?.getBoundingClientRect();
      if (!card || !panel || !bounds) return;
      const viewport = flow.getViewport();
      const position = absolutePosition(card, nodesRef.current);
      const top = position.y * viewport.zoom + viewport.y;
      const shelf = ["video","audio"].includes(card.data.kind||"") ? stage.current?.querySelector<HTMLElement>(`[data-id="${CSS.escape(selectedId)}"] .video-history`) : null;
      const height = (dimensions(card).height + (shelf ? shelf.offsetHeight + 12 : 0)) * viewport.zoom;
      const heading = stage.current?.querySelector<HTMLElement>(
        `[data-id="${CSS.escape(selectedId)}"] .media-node-heading`,
      );
      const minimumTop =
        (heading?.getBoundingClientRect().height || 24) +
        (imageTools.current?.offsetHeight || 0) +
        40;
      const body = panel.firstElementChild as HTMLElement | null;
      const naturalHeight = body
        ? Math.max(body.offsetHeight, body.scrollHeight + 2)
        : 310;
      const panelHeight = Math.min(
        naturalHeight,
        Math.max(190, bounds.height - minimumTop - height - 46),
      );
      const excess = top + height + 22 + panelHeight + 24 - bounds.height;
      const shift = Math.min(
        Math.max(0, top - minimumTop),
        Math.max(0, excess),
      );
      if (shift > 1)
        void flow.setViewport(
          { ...viewport, y: viewport.y - shift },
          { duration: 160 },
        );
    }, 180);
    return () => clearTimeout(timer);
  }, [composerNode?.id]);

  const updateGenerationDraft = useCallback(
    (draft: GenerationDraft) => {
      if (!selectedImage) return;
      updateData(selectedImage.id, { generation: draft });
    },
    [selectedImage?.id, updateData],
  );

  const removeGenerationConnections = useCallback(
    (edgeIds: string[]) => {
      edit(
        nodesRef.current,
        edgesRef.current.filter((edge) => !edgeIds.includes(edge.id) || edgeLocked(edge,nodesRef.current)),
      );
    },
    [edit],
  );
  const composerAction = (
    action: "edit" | "reference" | "mask" | "parameters",
  ) => {
    if (!selectedImage || imageEditingDisabled) return;
    window.dispatchEvent(
      new CustomEvent("manju:composer-action", {
        detail: { nodeId: selectedImage.id, action },
      }),
    );
  };
  useEffect(() => {
    let current = true;
    setSelectedAsset(null);
    setAssetDisplayName("");
    if (selectedVersionId)
      api<{ asset: Asset; version: AssetVersion }>(
        `/api/versions/${selectedVersionId}`,
      )
        .then((result) => {
          if (current) {
            setSelectedAsset(result.asset);
            setAssetDisplayName(result.asset.name);
          }
        })
        .catch((error) => {
          if (current) setNotice(errorText(error));
        });
    return () => {
      current = false;
    };
  }, [selectedVersionId, assetsRefresh]);
  const renameSelectedAsset = async () => {
    if (
      !selectedAsset ||
      renamingAsset ||
      !assetDisplayName.trim() ||
      assetDisplayName.trim() === selectedAsset.name
    )
      return;
    const projectId = project.id;
    const assetId = selectedAsset.id;
    setRenamingAsset(true);
    try {
      await api(`/api/assets/${assetId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: assetDisplayName.trim() }),
      });
      if (activeProjectRef.current !== projectId) return;
      setSelectedAsset((current) =>
        current?.id === assetId
          ? { ...current, name: assetDisplayName.trim() }
          : current,
      );
      setNotice("已更新资产显示名；节点名称保持独立。");
      void reloadAssets();
      onAssetsChange();
    } catch (error) {
      if (activeProjectRef.current === projectId) setNotice(errorText(error));
    } finally {
      if (activeProjectRef.current === projectId) setRenamingAsset(false);
    }
  };
  const getCanvasMedia = useCallback((): SubjectMediaCandidate[] => {
    const candidates: SubjectMediaCandidate[] = [];
    for (const node of nodesRef.current) {
      if (node.type === "subject" && node.data.subject) {
        const snapshot = node.data.subject;
        snapshot.image_version_ids.forEach((versionId, index) =>
          candidates.push({
            version_id: versionId,
            title: index
              ? `${snapshot.name} · 参考${index + 1}`
              : snapshot.name,
            kind: "image",
            node_id: node.id,
          }),
        );
        if (snapshot.kind === "character" && snapshot.voice_version_id)
          candidates.push({
            version_id: snapshot.voice_version_id,
            title: snapshot.voice_name || `${snapshot.name} · 音色`,
            kind: "audio",
            node_id: node.id,
          });
      } else if (
        node.type === "media" &&
        node.data.asset_version_id &&
        (node.data.kind === "image" || node.data.kind === "audio")
      ) {
        candidates.push({
          version_id: node.data.asset_version_id,
          title: node.data.title || "未命名素材",
          kind: node.data.kind,
          node_id: node.id,
        });
      }
    }
    return candidates;
  }, []);
  const updateSubject = useCallback(
    (id: string, snapshot: SubjectSnapshot) => {
      if (activeProjectRef.current !== project.id) return;
      const node = nodesRef.current.find((item) => item.id === id);
      if (node?.type !== "subject" || node.data.locked) return;
      remember();
      updateData(id, {
        subject: clone(snapshot),
        kind: "image",
        asset_version_id: snapshot.image_version_ids[0],
      });
      onAssetsChange();
    },
    [project.id, remember, updateData, onAssetsChange],
  );
  const displayedNodes = useMemo(() => {
    const collapsedGroups = nodes.filter(
      (node) => node.type === "group" && node.data.collapsed,
    );
    return nodes.map((node) => {
      const hidden = !!node.hidden || !!node.data.production_settings || collapsedGroups.some((parent) =>
        isDescendant(node, parent.id, nodes),
      );
      const collapsed = node.type === "group" && node.data.collapsed;
      return {
        ...node,
        hidden,
        className:[node.className,canvasPick && (canvasPick.kind==="image" ? !!node.data.asset_version_id && (node.type==="subject" || node.data.kind==="image") : node.data.kind==="audio" || !!node.data.subject?.voice_version_id) ? "canvas-pick-compatible":""].filter(Boolean).join(" "),
        draggable: !node.data.locked && !canvasPick,
        connectable: !node.data.locked,
        width: collapsed ? 260 : node.width,
        height: collapsed ? 54 : node.height,
        style: collapsed
          ? { ...node.style, width: 260, height: 54 }
          : node.style,
      };
    });
  }, [nodes,canvasPick]);
  const actions: CanvasActions = useMemo(
    () => ({
      projectId: project.id,
      flushCanvas,
      getCanvasMedia,
      preview: onPreview,
      updateSubject,
      beginEdit: remember,
      updateData,
      toggleGroup: (id: string) => {
        remember();
        const node = nodesRef.current.find((item) => item.id === id);
        if (node) updateData(id, { collapsed: !node.data.collapsed });
      },
      resizeStart: () => {
        remember();
        interactingRef.current = true;
      },
      resizeEnd: () => {
        interactingRef.current = false;
        if (dirtyRef.current) setChangeSerial(value => value + 1);
      },
    }),
    [
      project.id,
      flushCanvas,
      getCanvasMedia,
      onPreview,
      updateSubject,
      remember,
      updateData,
      changed,
    ],
  );

  const changeSelectionData = (patch: Partial<CanvasData>) =>
    edit(
      nodesRef.current.map((node) =>
        node.selected ? { ...node, data: { ...node.data, ...patch } } : node,
      ),
    );
  const setLayer = (front: boolean) => {
    const values = nodesRef.current.map((node) => node.zIndex || 0);
    const value = front
      ? Math.max(0, ...values) + 1
      : Math.min(0, ...values) - 1;
    edit(
      nodesRef.current.map((node) =>
        node.selected ? { ...node, zIndex: value } : node,
      ),
    );
  };
  const exportDraft = () => {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            project_id: project.id,
            revision: revisionRef.current,
            nodes: cleanNodes(nodesRef.current),
            edges: edgesRef.current,
            viewport: viewportRef.current,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${project.name}-画布草稿.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const reloadAfterConflict = () => {
    try {
      const draft = localStorage.getItem(draftKey);
      if (draft) {
        const backupKey = `${draftKey}:backup:${Date.now()}`;
        localStorage.setItem(backupKey, draft);
        setRecoverableDraft(backupKey);
      }
      localStorage.removeItem(draftKey);
    } catch {
      setNotice("本机草稿备份失败，请先下载草稿。");
      return;
    }
    void loadCanvas(false, true);
  };
  const restoreDraft = async (draft: RecoverableCanvas) => {
    await flushCanvas();
    const current = await api<CanvasDocument>(`/api/projects/${project.id}/canvas`);
    const selection = cloneCanvasSelection({nodes:draft.nodes.filter(node=>!node.data.production_settings && !node.data.timeline),edges:draft.edges});
    const payload = mergeCanvasSelection(current, selection, `restore-draft:${uid()}`);
    await api(`/api/projects/${project.id}/canvas`, {method:"PUT", body:JSON.stringify(payload)});
    await loadCanvas(false);
    setRecoverableDraft(null);
    setNotice(`已恢复 ${selection.nodes.length} 个节点副本，原画布与备份均已保留。`);
    await flow.fitView({nodes:selection.nodes.map(node=>({id:node.id})),padding:.2,maxZoom:1,duration:250});
  };
  const locateNode = (id:string) => {
    const node = nodesRef.current.find(item=>item.id===id);
    if (!node) return;
    const parents = new Set<string>();
    let parent = node.parentId;
    while (parent && !parents.has(parent)) {parents.add(parent);parent=nodesRef.current.find(item=>item.id===parent)?.parentId;}
    const expanded = nodesRef.current.some(item=>parents.has(item.id) && item.data.collapsed);
    const next=nodesRef.current.map(item=>({...item,selected:item.id===id,...(parents.has(item.id)?{data:{...item.data,collapsed:false}}:{})}));
    if(expanded)edit(next);else replace(next);
    suppressSelectionPan.current=id;
    const point=absolutePosition(node,nodesRef.current),size=dimensions(node);
    void flow.setCenter(point.x+size.width/2,point.y+size.height/2,{zoom:Math.min(1,stageDimensions.width/(size.width+180),stageDimensions.height/(size.height+180)),duration:250});
  };
  const renderFrame = async (frameId:string) => {
    setRenderingFrame(true);
    try {
      await flushCanvas();
      const result=await api<{asset_id:string;version_id:string;node_id:string}>(`/api/projects/${project.id}/frames/${frameId}/render-image`,{method:"POST",body:JSON.stringify({request_id:uid(),revision:revisionRef.current,scale:1})});
      await loadCanvas(false);onAssetsChange();void reloadAssets();
      setNotice("画框中的图片和文字已合成，结果已加入画布及资产库。");
      onPreview(result.version_id);
    } catch(error) {setNotice(errorText(error));}
    finally {setRenderingFrame(false);}
  };
  const referenceChanges = (node:CanvasNode) => {
    const refs=node.data.generation?.references||[];
    const changes=refs.flatMap((ref,index)=>{
      if(!ref.node_id)return [];
      const source=nodes.find(item=>item.id===ref.node_id);
      if(!source)return [{ref,index,missing:true,next:undefined}];
      const audio=ref.media_type==="audio" || node.data.kind==="audio";
      const versions=source.data.subject ? (audio?[source.data.subject.voice_version_id].filter(Boolean):source.data.subject.image_version_ids) : [source.data.asset_version_id];
      const next=(audio&&source.data.subject?source.data.subject.voice_version_id:source.data.asset_version_id);
      const changed=ref.source==="connection"?next!==ref.version_id:!versions.includes(ref.version_id);
      return changed ? [{ref,index,missing:!next,next}] : [];
    });
    return changes.length>0 && <div className="canvas-reference-changes" role="status">{changes.map(({ref,index,missing,next})=><div key={ref.id||index}><span>{ref.title}：{missing?"来源已移除或暂无素材，仍使用已固定版本":"来源素材已更新，当前仍使用旧版本"}</span><button onClick={()=>onPreview(ref.version_id)}>查看当前</button>{next&&<><button onClick={()=>onPreview(next)}>查看新版</button><button disabled={!!node.data.locked||!!node.data.generation?.pending_submission} onClick={()=>{remember();updateData(node.id,{generation:{...node.data.generation!,references:refs.map((item,i)=>i===index?{...item,version_id:next}:item)}});}}>采用新版参考</button></>}</div>)}</div>;
  };
  const removeProjectAsset = async () => {
    if (!removeAsset || removingAsset) return;
    if (dirtyRef.current) await save();
    if (dirtyRef.current || conflictRef.current || savingRef.current) {
      setNotice("请先完成画布保存，再移除项目资产。");
      return;
    }
    setRemovingAsset(true);
    removingAssetRef.current = true;
    try {
      const result = await api<{ canvas: CanvasDocument }>(
        `/api/projects/${project.id}/assets/${removeAsset.id}?remove_nodes=true`,
        { method: "DELETE" },
      );
      remember();
      revisionRef.current = result.canvas.revision;
      savedDocumentRef.current = clone(result.canvas);
      replace(result.canvas.nodes, result.canvas.edges);
      setRemoveAsset(null);
      void reloadAssets();
      onAssetsChange();
    } catch (error) {
      setNotice(errorText(error));
    } finally {
      removingAssetRef.current = false;
      setRemovingAsset(false);
    }
  };

  const openContextMenu = (
    event: React.MouseEvent | MouseEvent,
    node?: CanvasNode,
  ) => {
    if (
      loading ||
      (event.target instanceof Element &&
        event.target.closest('input,textarea,select,[contenteditable="true"]'))
    )
      return;
    event.preventDefault();
    event.stopPropagation();
    if (node) {
      suppressSelectionPan.current = node.id;
      if (!nodesRef.current.find((item) => item.id === node.id)?.selected)
        replace(
          nodesRef.current.map((item) => ({
            ...item,
            selected: item.id === node.id,
          })),
          edgesRef.current.map((edge) => ({ ...edge, selected: false })),
        );
    } else {
      replace(
        nodesRef.current.map((item) => ({ ...item, selected: false })),
        edgesRef.current.map((edge) => ({ ...edge, selected: false })),
      );
    }
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      position: flow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      }),
      kind: node ? "node" : "pane",
    });
  };
  const createEmptyGroup = (position: { x: number; y: number }) =>
    edit([
      ...nodesRef.current.map((node) => ({ ...node, selected: false })),
      {
        id: uid(),
        type: "group",
        position,
        style: { width: 480, height: 320 },
        data: { title: "新建分组", collapsed: false },
        selected: true,
        zIndex: -5,
      },
    ]);
  const canReadClipboard =
    !!clipboard.current?.nodes.length ||
    typeof navigator.clipboard?.read === "function" ||
    typeof navigator.clipboard?.readText === "function";
  const pasteMenuItem: CanvasMenuItem = {
    id: "paste",
    label: "粘贴",
    icon: <ClipboardPaste />,
    shortcut: "Ctrl+V",
    disabled: !canReadClipboard,
    hint: canReadClipboard ? undefined : "请先复制卡片，或使用 Ctrl+V 粘贴",
    onSelect: () => {
      if (contextMenu) void pasteAtPosition(contextMenu.position);
    },
  };
  const historyMenuItems: CanvasMenuItem[] = [
    {
      id: "undo",
      label: "撤销",
      icon: <Undo2 />,
      shortcut: "Ctrl+Z",
      disabled: !history.current.past.length,
      onSelect: undo,
    },
    {
      id: "redo",
      label: "重做",
      icon: <Redo2 />,
      shortcut: "Ctrl+Shift+Z",
      disabled: !history.current.future.length,
      onSelect: redo,
    },
  ];
  const menuItems: CanvasMenuItem[] = !contextMenu
    ? []
    : contextMenu.kind === "node"
      ? [
          {
            id: "copy",
            label: "复制",
            icon: <Copy />,
            shortcut: "Ctrl+C",
            onSelect: copySelection,
          },
          {
            id: "duplicate",
            label: "复制副本",
            icon: <Copy />,
            shortcut: "Ctrl+D",
            onSelect: () => {
              const snapshot = getSelectionSnapshot();
              if (snapshot) pasteSnapshot(snapshot);
            },
          },
          pasteMenuItem,
          { id: "save-divider", divider: true },
          {
            id: "save-canvas",
            label: "保存到其他画布",
            icon: <FolderInput />,
            onSelect: () => setSaveSelection(getSelectionSnapshot()),
          },
          {
            id: "save-subject",
            label: "保存到主体库",
            icon: <UserRoundPlus />,
            disabled:
              !selectedImage?.data.asset_version_id &&
              !selectedSubject?.data.subject?.image_version_ids.length,
            hint:
              selectedImage?.data.asset_version_id ||
              selectedSubject?.data.subject?.image_version_ids.length
                ? undefined
                : "请选择图片或含图片的主体；空主体需先添加图片",
            onSelect: () => {
              if (selectedSubject?.data.subject)
                setSubjectDraft(clone(selectedSubject.data.subject));
              else if (selectedImage?.data.asset_version_id)
                setSubjectDraft({
                  kind: "character",
                  image_version_ids: [selectedImage.data.asset_version_id],
                  name: selectedImage.data.title || "未命名主体",
                  description: selectedImage.data.note || "",
                });
            },
          },
          ...(selectedImage
            ? [
                {
                  id: "convert-subject",
                  label: "转为主体",
                  icon: <UserRound />,
                  disabled: !!selectedImage.data.locked,
                  hint: selectedImage.data.locked
                    ? "请先解锁图片卡片"
                    : undefined,
                  children: (
                    ["character", "scene", "prop"] as SubjectKind[]
                  ).map((kind) => {
                    const Icon = subjectKindIcons[kind];
                    return {
                      id: `convert-${kind}`,
                      label: subjectKindNames[kind],
                      icon: <Icon />,
                      onSelect: () => convertToSubject(selectedImage.id, kind),
                    };
                  }),
                },
              ]
            : []),
          {
            id: "download",
            label: single?.data.kind === "image" ? "下载图片" : "下载媒体原件",
            icon: <Download />,
            disabled: !single?.data.asset_version_id,
            hint: selected.length > 1 ? "一次选择一张卡片下载" : undefined,
            onSelect: () => {
              if (single?.data.asset_version_id) {
                const link = document.createElement("a");
                link.href = mediaUrl(
                  single.data.asset_version_id,
                  "original",
                  true,
                );
                link.download = single.data.title || "素材";
                link.click();
              }
            },
          },
          { id: "history-divider", divider: true },
          ...historyMenuItems,
          {
            id: "delete",
            label: "删除",
            icon: <Trash2 />,
            shortcut: "Delete",
            danger: true,
            disabled: selected.every((node) => node.data.locked),
            hint: selected.every((node) => node.data.locked)
              ? "请先在属性面板解锁"
              : undefined,
            onSelect: deleteSelection,
          },
        ]
      : [
          {
            id: "create",
            label: "新建节点",
            icon: <Plus />,
            children: [
              {
                id: "create-image",
                label: "图片生成",
                icon: <Sparkles />,
                onSelect: () => addGeneration(contextMenu.position),
              },
              {id:"create-audio",label:"人物配音",icon:<Music2/>,onSelect:()=>addSpeechGeneration(contextMenu.position)},
              {id:"create-video",label:"视频生成",icon:<Video/>,onSelect:()=>addVideoGeneration(contextMenu.position)},
              ...(["character", "scene", "prop"] as SubjectKind[]).map(
                (kind) => {
                  const Icon = subjectKindIcons[kind];
                  return {
                    id: `create-${kind}`,
                    label: subjectKindNames[kind],
                    icon: <Icon />,
                    onSelect: () => addEmptySubject(kind, contextMenu.position),
                  };
                },
              ),
              {
                id: "create-text",
                label: "文字",
                icon: <Type />,
                onSelect: () => addText(contextMenu.position),
              },
              {
                id: "create-group",
                label: "分组",
                icon: <Group />,
                onSelect: () => createEmptyGroup(contextMenu.position),
              },
              {
                id: "create-frame-horizontal",
                label: "横屏画框 16:9",
                icon: <Frame />,
                onSelect: () => addFrame("16:9", contextMenu.position),
              },
              {
                id: "create-frame-vertical",
                label: "竖屏画框 9:16",
                icon: <Frame />,
                onSelect: () => addFrame("9:16", contextMenu.position),
              },
              { id: "import-divider", divider: true },
              {
                id: "import-image",
                label: "导入图片",
                icon: <ImageIcon />,
                disabled: uploadProgress !== null,
                onSelect: () => openFilePicker(contextMenu.position, "image/*"),
              },
              {
                id: "import-video",
                label: "导入视频",
                icon: <Video />,
                disabled: uploadProgress !== null,
                onSelect: () => openFilePicker(contextMenu.position, "video/*"),
              },
              {
                id: "import-audio",
                label: "导入音频",
                icon: <Music2 />,
                disabled: uploadProgress !== null,
                onSelect: () => openFilePicker(contextMenu.position, "audio/*"),
              },
            ],
          },
          pasteMenuItem,
          { id: "history-divider", divider: true },
          ...historyMenuItems,
        ];

  return (
    <div className="canvas-workspace" data-history={historySerial}>
      <header className="canvas-topbar">
        <div className="canvas-title-area">
          <button
            className="canvas-icon-button back-button"
            title="返回项目"
            onClick={() => {
              if (dirtyRef.current) persistDraft();
              onBack();
            }}
          >
            <ArrowLeft size={19} />
          </button>
          <CanvasProjectMenu
            project={project}
            nodes={nodes}
            edgeCount={edges.length}
            revision={revisionRef.current}
            onProjectChange={onProjectChange}
            onNavigate={async id => {
              if (dirtyRef.current && !conflictRef.current) await flushCanvas();
              if (dirtyRef.current) persistDraft();
              window.location.hash = `/canvas/${encodeURIComponent(id)}`;
            }}
            onNotice={setNotice}
          />
        </div>
        <div className="canvas-header-actions">
          <span className={`canvas-save-status ${saveState}`}>
            {saveState === "saved" ? (
              <Check size={13} />
            ) : saveState === "saving" ? (
              <Loader2 className="spin" size={13} />
            ) : (
              <AlertCircle size={13} />
            )}
            {
              {
                saved: "已保存",
                pending: "待保存",
                saving: "保存中",
                error: "保存失败",
                conflict: "版本冲突",
              }[saveState]
            }
          </span>
          {saveState === "error" && (
            <button className="canvas-small-button" onClick={() => void save()}>
              重试保存
            </button>
          )}
          <button className="canvas-small-button canvas-production-button" onClick={()=>void flushCanvas().then(()=>setShowProduction(true)).catch(error=>setNotice(errorText(error)))}><Video size={15}/><span>分镜成片</span></button>
          <button className="canvas-small-button" onClick={()=>void flushCanvas().then(()=>setShowCanvasRun(true)).catch(error=>setNotice(errorText(error)))}>自动编排</button>
          <button className="canvas-small-button" onClick={()=>void flushCanvas().then(()=>setShowTimeline(true)).catch(error=>setNotice(errorText(error)))}>多轨剪辑</button>
          <button className="canvas-small-button" onClick={()=>void flushCanvas().then(()=>{setLipSyncNodeId(selectedVideo?.id);setShowLipSync(true);}).catch(error=>setNotice(errorText(error)))}>口型同步</button>
          <button className={`canvas-small-button ${showNavigator?"active":""}`} title="搜索画布节点" aria-label="搜索画布节点" aria-expanded={showNavigator} onClick={()=>setShowNavigator(value=>!value)}><Search size={15}/></button>
          <button
            className={`canvas-small-button canvas-panel-toggle ${showLibrary ? "active" : ""}`}
            title="素材面板"
            aria-label="素材面板"
            aria-expanded={showLibrary}
            onClick={() => setShowLibrary((value) => !value)}
          >
            <PanelLeft size={15} />
            <span>素材</span>
          </button>
          <button
            className={`canvas-small-button canvas-panel-toggle ${showInspector ? "active" : ""}`}
            title="属性面板"
            aria-label="属性面板"
            aria-expanded={showInspector}
            onClick={() => setShowInspector((value) => !value)}
          >
            <PanelRight size={15} />
            <span>属性</span>
          </button>
          <button
            className="canvas-small-button"
            onClick={onOpenTasks}
            aria-label="查看生成任务"
          >
            <ListChecks size={15} />
            任务
          </button>
          <button
            className="canvas-small-button canvas-comfy-button"
            onClick={onOpenComfy}
            aria-label="打开 ComfyUI 管理"
            title="管理本地 ComfyUI 服务"
          >
            <CircuitBoard size={14} />
            ComfyUI
          </button>
          <div
            className="canvas-more-menu"
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget))
                setShowMore(false);
            }}
          >
            <button
              className="canvas-icon-button"
              title="更多"
              aria-label="更多画布选项"
              aria-expanded={showMore}
              onClick={() => setShowMore((value) => !value)}
            >
              <Ellipsis size={20} />
            </button>
            {showMore && (
              <div className="canvas-more-options">
                <button
                  onClick={() => {
                    exportDraft();
                    setShowMore(false);
                  }}
                >
                  <Download size={14} />
                  导出画布
                </button>
                <button onClick={()=>{setShowDrafts(true);setShowMore(false);}}><FolderOpen size={14}/>草稿恢复 / 导入 JSON</button>
                <a href="#/workflows">
                  工作流库
                  <ChevronRight size={13} />
                </a>
                <a href="#/assets">
                  全局资产库
                  <ChevronRight size={13} />
                </a>
                <a href="#/settings">
                  设置
                  <ChevronRight size={13} />
                </a>
                <a href="#/trash">
                  回收站
                  <ChevronRight size={13} />
                </a>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="canvas-main">
        <aside className="canvas-library" hidden={!showLibrary}>
          <div className="canvas-panel-heading">
            <h2>素材</h2>
            <div className="canvas-panel-heading-actions">
              <button
                className="canvas-icon-button"
                title="导入素材"
                onClick={() => openFilePicker()}
                disabled={uploadProgress !== null}
              >
                <Plus size={17} />
              </button>
              <button
                className="canvas-icon-button"
                title="收起素材面板"
                onClick={() => setShowLibrary(false)}
              >
                <X size={15} />
              </button>
            </div>
          </div>
          <div className="canvas-library-tabs">
            <button
              className={assetScope === "project" ? "active" : ""}
              onClick={() => setAssetScope("project")}
            >
              项目资产
            </button>
            <button
              className={assetScope === "all" ? "active" : ""}
              onClick={() => setAssetScope("all")}
            >
              全部资产
            </button>
            <button
              className={assetScope === "subjects" ? "active" : ""}
              onClick={() => setAssetScope("subjects")}
            >
              主体库
            </button>
          </div>
          {assetScope === "subjects" ? (
            <SubjectLibrary
              refresh={subjectRefresh}
              onChoose={(subject) => void addSubject(subject)}
            />
          ) : (
            <>
              <label className="canvas-search">
                <Search size={14} />
                <input
                  placeholder="搜索素材"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <div className="canvas-asset-filters">
                {[
                  ["", "全部"],
                  ["image", "图片"],
                  ["video", "视频"],
                  ["audio", "音频"],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    className={assetFilter === value ? "active" : ""}
                    onClick={() => setAssetFilter(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="canvas-asset-list">
                {assetLoading && !assets.length ? (
                  <div className="canvas-library-empty">
                    <Loader2 size={20} className="spin" />
                    加载素材…
                  </div>
                ) : !assets.length ? (
                  <div className="canvas-library-empty">
                    <FolderOpen size={30} strokeWidth={1.2} />
                    <strong>
                      {search ? "没有找到素材" : "素材从这里开始"}
                    </strong>
                    <span>
                      {search
                        ? "试试其他关键词"
                        : "导入图片、视频或音频，拖到画布开始创作"}
                    </span>
                    {!search && (
                      <button
                        className="canvas-small-button"
                        onClick={() => openFilePicker()}
                      >
                        <Upload size={14} />
                        导入素材
                      </button>
                    )}
                  </div>
                ) : (
                  assets.map((asset) => (
                    <div
                      key={asset.id}
                      className="canvas-asset-card"
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData(
                          assetDragType,
                          JSON.stringify(asset),
                        );
                        event.dataTransfer.effectAllowed = "copy";
                      }}
                      onDoubleClick={() => onPreview(asset.current_version_id)}
                    >
                      <div
                        className={`canvas-asset-thumb ${asset.type === "audio" ? "is-audio" : ""}`}
                      >
                        {asset.type === "audio" ? (
                          <Music2 size={26} />
                        ) : (
                          <img
                            src={`${mediaUrl(asset.current_version_id)}&refresh=${mediaRevisions[asset.current_version_id] || 0}&status=${asset.version.preview_status}`}
                            alt=""
                            loading="lazy"
                            draggable={false}
                            onError={(event) => {
                              event.currentTarget.style.visibility = "hidden";
                            }}
                            onLoad={(event) => {
                              event.currentTarget.style.visibility = "visible";
                            }}
                          />
                        )}
                        <span className="canvas-asset-type">
                          {asset.type === "video" ? (
                            <Video size={12} />
                          ) : asset.type === "audio" ? (
                            <Music2 size={12} />
                          ) : (
                            <ImageIcon size={12} />
                          )}
                        </span>
                        <button
                          className="canvas-asset-add"
                          title="添加到画布"
                          onClick={() => void addMedia(asset)}
                        >
                          <Plus size={16} />
                        </button>
                      </div>
                      <div className="canvas-asset-caption">
                        <span className="canvas-asset-name" title={asset.name}>
                          {asset.name}
                        </span>
                        {assetScope === "project" && (
                          <button
                            className="canvas-asset-remove"
                            title="从项目移除素材"
                            onClick={() => setRemoveAsset(asset)}
                          >
                            <X size={12} />
                          </button>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
              <div className="canvas-library-footer">
                <span>{assetTotal} 个素材</span>
                {assetTotal > 60 ? (
                  <div className="canvas-asset-pages">
                    <button
                      title="上一页素材"
                      disabled={assetPage === 0}
                      onClick={() => setAssetPage((value) => value - 1)}
                    >
                      <ArrowLeft size={12} />
                    </button>
                    <span>
                      {assetPage + 1} / {Math.ceil(assetTotal / 60)}
                    </span>
                    <button
                      title="下一页素材"
                      disabled={(assetPage + 1) * 60 >= assetTotal}
                      onClick={() => setAssetPage((value) => value + 1)}
                    >
                      <ChevronRight size={12} />
                    </button>
                  </div>
                ) : (
                  <span>拖入画布使用</span>
                )}
              </div>
            </>
          )}
        </aside>

        <main
          className={`canvas-stage ${zoom<0.55?"is-overview":""} ${dragOver ? "is-drag-over" : ""}`}
          ref={stage}
          style={{"--port-size":String(Math.max(22,24/zoom))+"px"} as React.CSSProperties}
          onDragOver={(event) => {
            if (
              event.dataTransfer.types.includes("Files") ||
              event.dataTransfer.types.includes(assetDragType) ||
              event.dataTransfer.types.includes(SUBJECT_DRAG_TYPE)
            ) {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
              setDragOver(true);
            }
          }}
          onDragLeave={(event) => {
            if (
              !event.currentTarget.contains(
                event.relatedTarget as globalThis.Node,
              )
            )
              setDragOver(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            const position = flow.screenToFlowPosition({
              x: event.clientX,
              y: event.clientY,
            });
            const raw = event.dataTransfer.getData(assetDragType);
            const subject = event.dataTransfer.getData(SUBJECT_DRAG_TYPE);
            if (subject) {
              try {
                void addSubject(JSON.parse(subject), position);
              } catch {
                setNotice("主体拖放内容无法读取。");
              }
            } else if (raw) {
              try {
                void addMedia(JSON.parse(raw), position);
              } catch {
                setNotice("素材拖放内容无法读取。");
              }
            } else
              void importFiles(Array.from(event.dataTransfer.files), position);
          }}
        >
          <MediaRevisions.Provider value={mediaRevisions}>
            <Actions.Provider value={actions}>
              <ReactFlow<CanvasNode>
                onlyRenderVisibleElements
                reconnectRadius={Math.max(12,14/zoom)}
                elevateEdgesOnSelect
                nodes={displayedNodes}
                edges={displayedEdges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeContextMenu={(event, node) =>
                  openContextMenu(event, node)
                }
                onPaneContextMenu={(event) => openContextMenu(event)}
                onNodeClick={(_,node) => {
                  if(canvasPick){const options=getCanvasMedia().filter(item=>item.node_id===node.id && item.kind===canvasPick.kind);if(options.length===1){canvasPick.onChoose(options[0]);setCanvasPick(null);}else if(options.length>1)setPickOptions(options);else setNotice("请选择包含对应素材的卡片。");return;}
                  suppressSelectionPan.current = null;
                  closeContextMenu();
                }}
                onPaneClick={() => {
                  suppressSelectionPan.current = null;
                  closeContextMenu();
                }}
                onConnect={onConnect}
                onReconnectStart={(_,edge)=>{reconnectingEdge.current=edge;}}
                onReconnectEnd={()=>{reconnectingEdge.current=null;}}
                onReconnect={reconnectCanvasEdge}
                onEdgeContextMenu={(event,edge)=>{event.preventDefault();setEdgeMenu({x:event.clientX,y:event.clientY,id:edge.id});}}
                onConnectEnd={(event,state)=>{
                  if (state.isValid || !state.fromNode || state.fromHandle?.type!=="source") return;
                  if (!(event.target instanceof Element) || !event.target.closest(".react-flow__pane")) return;
                  const point="changedTouches" in event ? event.changedTouches[0] : event;
                  if (!state.fromNode.data.locked) setConnectionDrop({x:point.clientX,y:point.clientY,source:state.fromNode.id});
                }}
                isValidConnection={connection=>{
                  const source=nodesRef.current.find(node=>node.id===connection.source),target=nodesRef.current.find(node=>node.id===connection.target);
                  return !!source && !!target && source.id!==target.id && !source.data.locked && !target.data.locked && (!reconnectingEdge.current || edgeRole(reconnectingEdge.current)!=="reference" || canReference(source,target));
                }}
                defaultEdgeOptions={{
                  type: "default",
                  style: { stroke: "#565d60", strokeWidth: 1.2 },
                  labelStyle: { fill: "#cbd1ca", fontSize: 12 },
                  labelBgStyle: { fill: "#202323" },
                }}
                connectionLineType={ConnectionLineType.Bezier}
                connectionLineStyle={{ stroke: "#86adff", strokeWidth: 1.5 }}
                connectOnClick
                connectionRadius={24}
                onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
                onNodeMouseLeave={(_, node) =>
                  setHoveredNodeId((current) =>
                    current === node.id ? null : current,
                  )
                }
                onNodeDragStart={() => {
                  remember();
                  interactingRef.current = true;
                }}
                onNodeDragStop={() => {
                  interactingRef.current = false;
                  if (dirtyRef.current) setChangeSerial(value => value + 1);
                }}
                onSelectionDragStart={() => {
                  remember();
                  interactingRef.current = true;
                }}
                onSelectionDragStop={() => {
                  interactingRef.current = false;
                  if (dirtyRef.current) setChangeSerial(value => value + 1);
                }}
                onNodeDoubleClick={(_, node) => {
                  if(node.data.generation?.workflow_id==='builtin-latentsync15-local'){void flushCanvas().then(()=>{setLipSyncNodeId(node.id);setShowLipSync(true);}).catch(error=>setNotice(errorText(error)));return;}
                  if (node.type === "media" && node.data.asset_version_id)
                    onPreview(node.data.asset_version_id);
                  if(node.data.shot)void flushCanvas().then(()=>setShowProduction(true)).catch(error=>setNotice(errorText(error)));
                }}
                onMoveStart={(event) => {
                  if (event) {
                    manualViewportSerial.current += 1;
                    closeContextMenu();
                  }
                }}
                onMoveEnd={(_, viewport) => {
                  setZoom(viewport.zoom);
                  if (
                    !loading &&
                    JSON.stringify(viewportRef.current) !==
                      JSON.stringify(viewport)
                  ) {
                    viewportRef.current = viewport;
                    try { localStorage.setItem(viewKey, JSON.stringify(viewport)); }
                    catch { /* Browsing does not depend on storage availability. */ }
                  }
                }}
                onMove={(_, viewport) => setZoom(viewport.zoom)}
                defaultViewport={initialViewport}
                minZoom={0.12}
                maxZoom={8}
                deleteKeyCode={null}
                selectionOnDrag={tool === "select"}
                panOnDrag={tool === "pan" ? [0, 1] : [1]}
                panOnScroll={false}
                zoomOnScroll
                zoomOnPinch
                selectionMode={SelectionMode.Partial}
                multiSelectionKeyCode={["Shift", "Control", "Meta"]}
                panActivationKeyCode="Space"
                colorMode="dark"
                proOptions={{ hideAttribution: true }}
                elevateNodesOnSelect={false}
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  color="#34363d"
                  gap={22}
                  size={0.9}
                />
              </ReactFlow>
            </Actions.Provider>
          </MediaRevisions.Provider>
          {!loading && !nodes.length && !loadError && (
            <div className="canvas-empty-state">
              <div className="canvas-empty-art">
                <ImageIcon size={31} strokeWidth={1.2} />
                <span>
                  <Plus size={17} />
                </span>
              </div>
              <h2>让灵感在这里展开</h2>
              <p>拖入素材，或添加文字开始整理你的故事</p>
              <div className="canvas-empty-actions">
                <button onClick={() => addGeneration()}>
                  <Sparkles size={15} />
                  生成图片
                </button>
                <button onClick={() => openFilePicker()}>
                  <Upload size={15} />
                  导入素材
                </button>
              </div>
              <span className="canvas-empty-tip">
                支持图片、视频、音频 · 所有素材保存在本机
              </span>
            </div>
          )}
          {selectedImage?.data.asset_version_id && !loading && (
            <div
              ref={imageTools}
              className="canvas-image-tools nodrag nopan nowheel"
              role="toolbar"
              aria-label="图片操作"
              style={{
                left: imageToolsLeft,
                top: imageToolsTop,
                maxWidth: availableOverlayWidth,
                visibility: imageVisible ? "visible" : "hidden",
              }}
              onPointerDown={(event) => event.stopPropagation()}
              onDoubleClick={(event) => event.stopPropagation()}
            >
              <button
                className={
                  (selectedImage.data.generation?.mode || "edit") === "edit"
                    ? "is-active"
                    : ""
                }
                disabled={imageEditingDisabled}
                onClick={() => composerAction("edit")}
                title="用文字编辑当前图片"
              >
                <Pencil size={15} />
                <span>图片编辑</span>
              </button>
              <button
                className={
                  selectedImage.data.generation?.mode === "reference"
                    ? "is-active"
                    : ""
                }
                disabled={imageEditingDisabled}
                onClick={() => composerAction("reference")}
                title="以当前图片作为参考生成"
              >
                <Images size={15} />
                <span>参考生图</span>
              </button>
              <button
                disabled={imageEditingDisabled}
                onClick={() => composerAction("mask")}
                title="绘制蒙版，仅重绘指定区域"
              >
                <Brush size={15} />
                <span>局部重绘</span>
              </button>
              <button disabled={imageEditingDisabled} title="以当前图片为首帧生成视频" onClick={()=>addVideoGeneration({x:imagePosition.x+imageSize.width+100,y:imagePosition.y},selectedImage.id)}><Video size={15}/><span>生成视频</span></button>
              <span className="canvas-image-tools-divider" />
              <button
                className="icon-only"
                disabled={imageEditingDisabled}
                onClick={() => composerAction("parameters")}
                aria-label="调整生成参数"
                title="生成参数"
              >
                <SlidersHorizontal size={16} />
              </button>
              <a
                className="icon-only"
                href={mediaUrl(
                  selectedImage.data.asset_version_id,
                  "original",
                  true,
                )}
                download={selectedImage.data.title || "图片"}
                aria-label="下载当前图片"
                title="下载当前图片原件"
              >
                <Download size={16} />
              </a>
              <button
                className={`icon-only ${showInspector ? "is-active" : ""}`}
                onClick={() => setShowInspector((value) => !value)}
                aria-label="查看图片属性"
                title="图片属性"
              >
                <PanelRight size={16} />
              </button>
              <button
                className="icon-only"
                aria-label="图片更多操作"
                title="更多操作"
                onClick={(event) => {
                  const rect = event.currentTarget.getBoundingClientRect();
                  suppressSelectionPan.current = selectedImage.id;
                  setContextMenu({
                    x: rect.right - 254,
                    y: rect.bottom + 8,
                    position: flow.screenToFlowPosition({
                      x: rect.right,
                      y: rect.bottom,
                    }),
                    kind: "node",
                  });
                }}
              >
                <Ellipsis size={18} />
              </button>
            </div>
          )}
          {selectedVideo && selectedVideo.data.generation?.workflow_id!=="builtin-latentsync15-local" && !loading && <div ref={composerAnchor} className="video-composer-anchor" style={{left:composerLeft,top:composerTop,width:composerWidth,maxHeight:composerMaxHeight,visibility:imageVisible?"visible":"hidden"}}><div className="canvas-av-composer">{referenceChanges(selectedVideo)}<VideoComposer key={selectedVideo.id} projectId={project.id} nodeId={selectedVideo.id} draft={selectedVideo.data.generation} locked={selectedVideo.data.locked} canvasReferences={videoReferences} onChange={draft=>updateData(selectedVideo.id,{generation:draft})} onBeginEdit={remember} onBeforeSubmit={flushCanvas} onRemoveConnections={ids=>edit(nodesRef.current,edgesRef.current.filter(edge=>!ids.includes(edge.id)||edgeLocked(edge,nodesRef.current)))} onAssetsChange={onAssetsChange}/></div></div>}
          {selectedVideo?.data.generation?.workflow_id==='builtin-latentsync15-local' && !loading && <div className="video-composer-anchor" style={{left:composerLeft,top:composerTop,width:composerWidth,visibility:imageVisible?'visible':'hidden'}}><section className="video-composer nodrag nopan nowheel" aria-label="口型节点"><strong>LatentSync · 口型同步</strong><p>此卡片保存视频、配音与人脸定位参数。</p><button className="button secondary" onClick={()=>void flushCanvas().then(()=>{setLipSyncNodeId(selectedVideo.id);setShowLipSync(true);}).catch(error=>setNotice(errorText(error)))}>编辑口型节点</button></section></div>}
          {selectedAudio && !loading && <div ref={composerAnchor} className="video-composer-anchor" style={{left:composerLeft,top:composerTop,width:composerWidth,maxHeight:composerMaxHeight,visibility:imageVisible?"visible":"hidden"}}><div className="canvas-av-composer">{referenceChanges(selectedAudio)}<AudioComposer key={selectedAudio.id} projectId={project.id} nodeId={selectedAudio.id} draft={selectedAudio.data.generation} locked={selectedAudio.data.locked} canvasReferences={videoReferences.filter(r=>r.media_type==="audio"&&r.node_id!==selectedAudio.id)} onChange={draft=>updateData(selectedAudio.id,{generation:draft})} onBeginEdit={remember} onBeforeSubmit={flushCanvas} onRemoveConnections={ids=>edit(nodesRef.current,edgesRef.current.filter(edge=>!ids.includes(edge.id)||edgeLocked(edge,nodesRef.current)))} onAssetsChange={onAssetsChange}/></div></div>}
          {selectedImage && !loading && (
            <div
              ref={composerAnchor}
              className="generation-anchor"
              style={{
                left: composerLeft,
                top: composerTop,
                width: composerWidth,
                maxHeight: composerMaxHeight,
                visibility: imageVisible ? "visible" : "hidden",
              }}
            >
              <GenerationComposer
                key={selectedImage.id}
                projectId={project.id}
                nodeId={selectedImage.id}
                title={selectedImage.data.title || "图片创作"}
                versionId={(selectedImage.data.generation?.mode==="edit" ? selectedImage.data.generation?.edit_base_version_id : undefined) || selectedImage.data.asset_version_id}
                draft={selectedImage.data.generation}
                connections={generationConnections}
                unresolvedConnections={unresolvedEdges.length}
                onConfirmConnections={(role)=>edit(nodesRef.current,edgesRef.current.map(edge=>unresolvedEdges.some(item=>item.id===edge.id) && !edgeLocked(edge,nodesRef.current) ? {...edge,data:{...edge.data,role}}:edge))}
                onUpdateReference={(reference)=>{
                  const source=nodesRef.current.find(node=>node.id===reference.node_id);
                  if (!source?.data.asset_version_id || !selectedImage) return;
                  remember();
                  updateData(selectedImage.id,{generation:{...selectedImage.data.generation!,references:(selectedImage.data.generation?.references||[]).map(ref=>(ref.id || "ref-"+ref.version_id)===(reference.id || "ref-"+reference.version_id) ? {...ref,id:ref.id || "ref-"+ref.version_id,version_id:ref.source!=="connection" && source.data.subject?.image_version_ids.includes(ref.version_id) ? ref.version_id : source.data.asset_version_id!,description:source.data.subject?.description || ref.description}:ref)}});
                }}
                canvasReferences={canvasReferences}
                sourceImages={Object.fromEntries(nodes.map(node=>[node.id,node.data.subject?.image_version_ids || [node.data.asset_version_id].filter(Boolean) as string[]]))}
                sourceDescriptions={Object.fromEntries(nodes.filter(node=>node.data.subject).map(node=>[node.id,node.data.subject!.description]))}
                sourceVersions={Object.fromEntries(nodes.filter(node=>node.data.asset_version_id).map(node=>[node.id,node.data.asset_version_id!]))}
                locked={!!selectedImage.data.locked}
                position={{
                  x: imagePosition.x + imageSize.width + 90,
                  y: imagePosition.y,
                }}
                onChange={updateGenerationDraft}
                onBeginEdit={remember}
                onRemoveConnections={removeGenerationConnections}
                onBeforeSubmit={flushCanvas}
                onReveal={(id) => {
                  const node = nodesRef.current.find((item) => item.id === id);
                  if (!node) {
                    void synchronizeGeneration().then(() =>
                      flow.fitView({
                        nodes: [{ id }],
                        padding: 0.3,
                        maxZoom: 1,
                        duration: 300,
                      }),
                    );
                    return;
                  }
                  replace(
                    nodesRef.current.map((item) => ({
                      ...item,
                      selected: item.id === id,
                    })),
                  );
                  void flow.fitView({
                    nodes: [{ id }],
                    padding: 0.4,
                    maxZoom: 1,
                    duration: 300,
                  });
                }}
                onAssetsChange={onAssetsChange}
              />
            </div>
          )}
          {loading && (
            <div className="canvas-loading">
              <Loader2 className="spin" size={22} />
              <span>正在打开画布</span>
            </div>
          )}
          {loadError && (
            <div className="canvas-loading">
              <AlertCircle size={24} />
              <p>{loadError}</p>
              <button
                className="canvas-small-button"
                onClick={() => void loadCanvas()}
              >
                重新加载
              </button>
            </div>
          )}
          {dragOver && (
            <div className="canvas-drop-overlay">
              <Upload size={28} />
              <span>松开，将素材放到这里</span>
            </div>
          )}
          <div className="canvas-toolbar">
            <button title="生成视频" onClick={()=>addVideoGeneration()}><Video size={19}/></button>
            <button title="人物配音" onClick={()=>addSpeechGeneration()}><Music2 size={19}/></button>
            <button
              className="canvas-generate-tool"
              title="生成图片"
              onClick={() => addGeneration()}
            >
              <Sparkles size={19} />
            </button>
            <button
              title="选择 V"
              className={tool === "select" ? "active" : ""}
              onClick={() => setTool("select")}
            >
              <MousePointer2 size={19} />
            </button>
            <button
              title="平移画布，也可按住空格"
              className={tool === "pan" ? "active" : ""}
              onClick={() => setTool("pan")}
            >
              <Expand size={19} />
            </button>
            <span className="toolbar-divider" />
            <button title="文字 T" onClick={() => addText()}>
              <Type size={20} />
            </button>
            <div className="canvas-frame-menu">
              <button
                title="新建主体"
                aria-label="新建主体"
                aria-expanded={showSubjects}
                className={showSubjects ? "active" : ""}
                onClick={() => {
                  setShowSubjects(!showSubjects);
                  setShowFrames(false);
                }}
              >
                <UserRoundPlus size={19} />
              </button>
              {showSubjects && (
                <div className="canvas-frame-options canvas-subject-options">
                  {(["character", "scene", "prop"] as SubjectKind[]).map(
                    (kind) => {
                      const Icon = subjectKindIcons[kind];
                      return (
                        <button
                          key={kind}
                          onClick={() => addEmptySubject(kind)}
                        >
                          <Icon size={15} />
                          {subjectKindNames[kind]}
                        </button>
                      );
                    },
                  )}
                </div>
              )}
            </div>
            <div className="canvas-frame-menu">
              <button
                title="添加画框"
                className={showFrames ? "active" : ""}
                onClick={() => {
                  setShowFrames(!showFrames);
                  setShowSubjects(false);
                }}
              >
                <Frame size={19} />
              </button>
              {showFrames && (
                <div className="canvas-frame-options">
                  <button onClick={() => addFrame("16:9")}>横屏 16:9</button>
                  <button onClick={() => addFrame("9:16")}>竖屏 9:16</button>
                </div>
              )}
            </div>
            <button
              title="导入素材"
              onClick={() => openFilePicker()}
              disabled={uploadProgress !== null}
            >
              <ImageIcon size={20} />
            </button>
            <button
              title="创建分组 Ctrl+G"
              onClick={groupSelection}
              disabled={!selected.length}
            >
              <Group size={19} />
            </button>
            <span className="toolbar-divider" />
            <button
              title="撤销 Ctrl+Z"
              onClick={undo}
              disabled={!history.current.past.length}
            >
              <Undo2 size={18} />
            </button>
            <button
              title="重做 Ctrl+Shift+Z"
              onClick={redo}
              disabled={!history.current.future.length}
            >
              <Redo2 size={18} />
            </button>
          </div>
          <div className="canvas-zoom-controls">
            <button title="缩小" onClick={() => void flow.zoomOut()}>
              <Minus size={15} />
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button title="放大" onClick={() => void flow.zoomIn()}>
              <Plus size={15} />
            </button>
            <span className="toolbar-divider" />
            <button
              title="适应全部内容"
              onClick={() =>
                void flow.fitView({
                  padding: 0.18,
                  duration: 250,
                  maxZoom: 1.2,
                })
              }
            >
              <Maximize size={16} />
            </button>
          </div>
          {showNavigator && <section className="canvas-node-navigator nodrag nopan nowheel" aria-label="画布节点导航"><header><Search size={15}/><input autoFocus aria-label="搜索节点名称和内容" placeholder="搜索节点、角色或台词" value={nodeSearch} onChange={event=>setNodeSearch(event.target.value)}/><button title="关闭节点导航" onClick={()=>setShowNavigator(false)}><X size={16}/></button></header><div>{nodes.filter(node=>!node.data.production_settings && [node.data.title,node.data.text,node.data.subject?.name,node.data.generation?.prompt].some(value=>String(value||"").toLowerCase().includes(nodeSearch.toLowerCase()))).slice(0,100).map(node=><button key={node.id} onClick={()=>locateNode(node.id)}><span>{node.data.title||node.data.subject?.name||node.type||"节点"}</span><small>{node.data.shot?"分镜":node.data.kind||node.type}</small></button>)}</div><footer>选择条目定位节点 · 最多显示 100 个匹配项</footer></section>}
          <div className="canvas-stage-status">
            <span className="canvas-status-dot" />
            {nodes.length} 个元素
            <span className="canvas-keyboard-hint">空格拖动 · 滚轮缩放</span>
          </div>
        </main>

        <aside className="canvas-inspector" hidden={!showInspector}>
          <div className="canvas-panel-heading">
            <h2>{selected.length ? "属性" : selectedEdge ? "连线" : "画布"}</h2>
            <button
              className="canvas-icon-button"
              title="收起属性面板"
              onClick={() => setShowInspector(false)}
            >
              <X size={15} />
            </button>
          </div>
          {selected.length > 0 ? (
            <>
              <div className="canvas-inspector-section">
                <span className="canvas-section-caption">
                  {single
                    ? {
                        media: "媒体素材",
                        subject: "主体卡片",
                        text: "文字备注",
                        group: "分组",
                        frame: "画框",
                      }[single.type || ""] || "元素"
                    : `已选择 ${selected.length} 个元素`}
                </span>
                {single && (
                  <>
                    <label className="canvas-field">
                      节点名称
                      <input
                        aria-label="节点名称"
                        value={single.data.title || ""}
                        maxLength={250}
                        disabled={!!single.data.locked}
                        onFocus={remember}
                        onChange={(event) =>
                          updateData(single.id, { title: event.target.value })
                        }
                      />
                    </label>
                    {(single.type==="media" || single.type==="text") && <label className="canvas-field">合成不透明度<input type="number" aria-label="合成不透明度" min={0} max={1} step={.05} value={Number(single.data.opacity??1)} disabled={!!single.data.locked} onFocus={remember} onChange={event=>{const opacity=Number(event.target.value);if(Number.isFinite(opacity)&&opacity>=0&&opacity<=1)updateData(single.id,{opacity});}}/></label>}
                    {single.type==="frame" && <button className="canvas-small-button" disabled={renderingFrame} onClick={()=>void renderFrame(single.id)}><Download size={14}/>{renderingFrame?"合成中…":"合成画框图片"}<small>图片与文字</small></button>}
                    <div className="canvas-field-grid">
                      {(["width", "height"] as const).map((key) => (
                        <label className="canvas-field" key={key}>
                          {key === "width" ? "宽度" : "高度"}
                          <input
                            type="number"
                            min={90}
                            value={Math.round(dimensions(single)[key])}
                            disabled={!!single.data.locked}
                            onFocus={remember}
                            onChange={(event) => {
                              const size = Number(event.target.value);
                              if (!Number.isFinite(size) || size < 90) return;
                              replace(
                                nodesRef.current.map((node) =>
                                  node.id === single.id
                                    ? {
                                        ...node,
                                        [key]: size,
                                        style: { ...node.style, [key]: size },
                                      }
                                    : node,
                                ),
                              );
                              changed();
                            }}
                          />
                        </label>
                      ))}
                    </div>
                  </>
                )}
              </div>
              <div className="canvas-inspector-section">
                <span className="canvas-section-caption">排列</span>
                <div className="canvas-align-tools">
                  {[
                    { mode: "left", Icon: AlignLeft, title: "左对齐" },
                    {
                      mode: "center-x",
                      Icon: AlignCenterHorizontal,
                      title: "水平居中",
                    },
                    { mode: "right", Icon: AlignRight, title: "右对齐" },
                    {
                      mode: "top",
                      Icon: AlignStartVertical,
                      title: "顶部对齐",
                    },
                    {
                      mode: "center-y",
                      Icon: AlignCenterVertical,
                      title: "垂直居中",
                    },
                    {
                      mode: "bottom",
                      Icon: AlignEndVertical,
                      title: "底部对齐",
                    },
                    {
                      mode: "distribute-x",
                      Icon: BetweenHorizontalStart,
                      title: "水平等距",
                    },
                    {
                      mode: "distribute-y",
                      Icon: BetweenVerticalStart,
                      title: "垂直等距",
                    },
                  ].map(({ mode, Icon, title }) => (
                    <button
                      key={mode}
                      title={title}
                      disabled={
                        selected.length <
                        (mode.startsWith("distribute") ? 3 : 2)
                      }
                      onClick={() => alignSelection(mode)}
                    >
                      <Icon size={16} />
                    </button>
                  ))}
                </div>
                <div className="canvas-property-actions">
                  <button onClick={() => setLayer(true)}>
                    <ArrowUp size={14} />
                    置于顶层
                  </button>
                  <button onClick={() => setLayer(false)}>
                    <ArrowDown size={14} />
                    置于底层
                  </button>
                  <button
                    onClick={() =>
                      changeSelectionData({
                        locked: !selected.every((node) => node.data.locked),
                      })
                    }
                  >
                    {selected.every((node) => node.data.locked) ? (
                      <Unlock size={14} />
                    ) : (
                      <Lock size={14} />
                    )}
                    {selected.every((node) => node.data.locked)
                      ? "解锁"
                      : "锁定"}
                  </button>
                  <button
                    onClick={() => {
                      copySelection();
                      if (clipboard.current) pasteSnapshot(clipboard.current);
                    }}
                  >
                    <Copy size={14} />
                    复制
                  </button>
                  <button onClick={groupSelection}>
                    <Group size={14} />
                    创建分组
                  </button>
                  <button
                    disabled={!selected.some((node) => node.type === "group")}
                    onClick={ungroupSelection}
                  >
                    <Ungroup size={14} />
                    解除分组
                  </button>
                </div>
              </div>
              {single && (
                <div className="canvas-inspector-section">
                  {single.type === "media" &&
                    single.data.asset_version_id &&
                    selectedAsset && (
                      <label className="canvas-field">
                        选用版本
                        <StudioSelect
                          value={single.data.asset_version_id}
                          onChange={(event) => {
                            remember();
                            updateData(single.id, {
                              asset_version_id: event.target.value,
                              generation_id: single.data.image_history?.find(
                                (item) =>
                                  item.version_id === event.target.value,
                              )?.job_id,
                              image_history:
                                single.data.image_history?.length &&
                                !single.data.image_history.some(
                                  (item) =>
                                    item.version_id === event.target.value,
                                )
                                  ? [
                                      ...single.data.image_history,
                                      { version_id: event.target.value },
                                    ]
                                  : single.data.image_history,
                            });
                          }}
                          disabled={!!single.data.locked}
                        >
                          {(
                            selectedAsset.versions || [selectedAsset.version]
                          ).map((version, index, versions) => (
                            <option key={version.id} value={version.id}>
                              版本 {versions.length - index} ·{" "}
                              {version.filename}
                            </option>
                          ))}
                        </StudioSelect>
                      </label>
                    )}
                  {selectedAsset && (
                    <div className="canvas-asset-name-editor">
                      <label className="canvas-field">
                        资产显示名
                        <input
                          aria-label="资产显示名"
                          value={assetDisplayName}
                          maxLength={250}
                          disabled={renamingAsset}
                          onChange={(event) =>
                            setAssetDisplayName(event.target.value)
                          }
                          onKeyDown={(event) => {
                            if (
                              event.key === "Enter" &&
                              !event.nativeEvent.isComposing
                            ) {
                              event.preventDefault();
                              void renameSelectedAsset();
                            }
                          }}
                        />
                      </label>
                      <button
                        className="canvas-wide-button"
                        disabled={
                          renamingAsset ||
                          !assetDisplayName.trim() ||
                          assetDisplayName.trim() === selectedAsset.name
                        }
                        onClick={() => void renameSelectedAsset()}
                      >
                        {renamingAsset ? (
                          <Loader2 size={13} className="spin" />
                        ) : (
                          <Check size={13} />
                        )}
                        保存资产名称
                      </button>
                      <small>修改资产库中的名称，不改变节点名称。</small>
                    </div>
                  )}
                  {single.type !== "subject" && (
                    <label className="canvas-field">
                      备注
                      <textarea
                        placeholder="添加素材说明…"
                        value={single.data.note || ""}
                        onFocus={remember}
                        onChange={(event) =>
                          updateData(single.id, { note: event.target.value })
                        }
                      />
                    </label>
                  )}
                  {single.data.asset_version_id && (
                    <button
                      className="canvas-wide-button"
                      onClick={() => onPreview(single.data.asset_version_id!)}
                    >
                      <Expand size={14} />
                      打开素材预览
                    </button>
                  )}
                </div>
              )}
              <div className="canvas-inspector-bottom">
                <button
                  className="canvas-delete-button"
                  onClick={deleteSelection}
                >
                  <Trash2 size={14} />
                  移除选中元素
                </button>
                <span>素材仍保留在资产库</span>
              </div>
            </>
          ) : selectedEdge ? (
            <div className="canvas-inspector-section">
              <p className="canvas-section-caption">拖动连线两端的圆点重接，或在下方选择节点。</p>
              {(["source","target"] as const).map(endpoint=><label className="canvas-field" key={endpoint}>{endpoint==="source"?"连接来源":"连接目标"}<StudioSelect aria-label={endpoint==="source"?"连接来源":"连接目标"} disabled={edgeLocked(selectedEdge,nodes)} value={selectedEdge[endpoint]} onChange={event=>reconnectCanvasEdge(selectedEdge,{source:selectedEdge.source,target:selectedEdge.target,sourceHandle:selectedEdge.sourceHandle||"out",targetHandle:selectedEdge.targetHandle||"in",[endpoint]:event.target.value})}>{nodes.filter(node=>!node.data.production_settings && !node.data.locked && node.id!==selectedEdge[endpoint==="source"?"target":"source"] && (edgeRole(selectedEdge)!=="reference" || canReference(endpoint==="source"?node:nodes.find(item=>item.id===selectedEdge.source),endpoint==="target"?node:nodes.find(item=>item.id===selectedEdge.target)))).map(node=><option key={node.id} value={node.id}>{node.data.title||node.data.subject?.name||node.type||node.id}</option>)}</StudioSelect></label>)}
              <label className="canvas-field">连线用途<StudioSelect aria-label="连线用途" disabled={edgeLocked(selectedEdge,nodes)} value={edgeRole(selectedEdge)} onChange={event=>changeEdgeRole(selectedEdge.id,event.target.value)}><option value="pending" disabled>用途待确认</option><option value="relation">故事关系</option><option value="reference">图片参考</option></StudioSelect></label>
              <label className="canvas-field">
                连线文字
                <input
                  disabled={edgeLocked(selectedEdge,nodes)}
                  value={String(selectedEdge.label || "")}
                  placeholder="填写关系说明"
                  onFocus={remember}
                  onChange={(event) => {
                    replace(
                      nodesRef.current,
                      edgesRef.current.map((edge) =>
                        edge.id === selectedEdge.id
                          ? { ...edge, label: event.target.value }
                          : edge,
                      ),
                    );
                    changed();
                  }}
                />
              </label>
              <button
                className="canvas-delete-button"
                onClick={deleteSelection}
              >
                <Trash2 size={14} />
                删除连线
              </button>
            </div>
          ) : (
            <>
              <div className="canvas-inspector-section">
                <span className="canvas-section-caption">项目设置</span>
                <div className="canvas-project-info">
                  <span>画幅</span>
                  <strong>{project.aspect_ratio || "16:9"}</strong>
                </div>
                <div className="canvas-project-info">
                  <span>元素</span>
                  <strong>{nodes.length}</strong>
                </div>
              </div>
              <div className="canvas-inspector-empty">
                <MousePointer2 size={24} strokeWidth={1.2} />
                <p>选择元素以查看和编辑属性</p>
              </div>
              <div className="canvas-shortcuts">
                <span>快捷操作</span>
                <div>
                  <span>文字</span>
                  <kbd>T</kbd>
                </div>
                <div>
                  <span>创建分组</span>
                  <kbd>Ctrl G</kbd>
                </div>
                <div>
                  <span>撤销</span>
                  <kbd>Ctrl Z</kbd>
                </div>
                <div>
                  <span>多选</span>
                  <kbd>Shift</kbd>
                </div>
              </div>
            </>
          )}
        </aside>
      </div>
      {saveState === "conflict" && (
        <div className="canvas-conflict-banner">
          <AlertCircle size={18} />
          <span>服务端已有新版本，当前修改已保存在本机草稿。</span>
          <button onClick={exportDraft}>下载草稿</button>
          <button onClick={reloadAfterConflict}>备份草稿并加载最新</button>
        </div>
      )}
      {recoverableDraft && saveState === "saved" && (
        <div className="canvas-conflict-banner canvas-recovery-banner">
          <FolderOpen size={17} />
          <span>发现未完成草稿或冲突备份，可以预览并恢复。</span>
          <button onClick={()=>setShowDrafts(true)}>查看恢复草稿</button>
          <button onClick={() => setRecoverableDraft(null)}>暂不恢复</button>
        </div>
      )}
      {notice && (
        <div className="canvas-notice">
          <AlertCircle size={16} />
          <span>{notice}</span>
          <button title="关闭提示" onClick={() => setNotice("")}>
            <X size={14} />
          </button>
        </div>
      )}
      {uploadProgress !== null && (
        <div className="canvas-upload-progress">
          <Loader2 size={17} className="spin" />
          <span>导入素材 {uploadProgress}%</span>
          <progress value={uploadProgress} max={100} />
        </div>
      )}
      {failedUploads.length > 0 && uploadProgress === null && (
        <div className="canvas-upload-progress">
          <AlertCircle size={17} />
          <span>{failedUploads.length} 个素材导入失败</span>
          <button
            className="canvas-small-button"
            onClick={async () => {
              const failures = failedUploads;
              setFailedUploads([]);
              for (const failed of failures)
                await importFiles([failed.file], failed.position);
            }}
          >
            重试
          </button>
          <button
            className="canvas-icon-button"
            title="关闭失败提示"
            onClick={() => setFailedUploads([])}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {removeAsset && (
        <Confirm
          title="从项目移除素材"
          description={`将从本项目移除「${removeAsset.name}」及画布中的相关卡片，之后可以从全局资产库再次添加。`}
          onClose={() => {
            if (!removingAsset) setRemoveAsset(null);
          }}
          onConfirm={() => void removeProjectAsset()}
          busy={removingAsset}
        />
      )}
      {canvasPick && <div className="canvas-pick-banner" role="status">点击画布中的{canvasPick.kind==="image"?"图片或主体":"音频或人物音色"} · Esc 取消 <button onClick={()=>{setCanvasPick(null);setPickOptions([]);}}>取消选择</button>{pickOptions.length>0 && <div className="canvas-pick-options">{pickOptions.map(item=><button key={item.version_id} onClick={()=>{canvasPick.onChoose(item);setCanvasPick(null);setPickOptions([]);}}>{item.kind==="image" && <img src={mediaUrl(item.version_id)} />}{item.title}</button>)}</div>}</div>}
      {connectionDrop && <CanvasContextMenu position={connectionDrop} onClose={()=>setConnectionDrop(null)} items={[
        {id:"image",label:"新建图片创作卡",disabled:!nodes.find(node=>node.id===connectionDrop.source)?.data.asset_version_id,onSelect:()=>createFromConnection("media")},
        {id:"text",label:"新建文字关系卡",onSelect:()=>createFromConnection("text")},
      ]} />}
        {edgeMenu && edges.some(edge=>edge.id===edgeMenu.id) && <CanvasContextMenu position={edgeMenu} onClose={()=>setEdgeMenu(null)} items={[
        {id:"reference",label:"作为图片参考",disabled:edgeLocked(edges.find(edge=>edge.id===edgeMenu.id)!,nodes),onSelect:()=>changeEdgeRole(edgeMenu.id,"reference")},
        {id:"relation",label:"作为故事关系",disabled:edgeLocked(edges.find(edge=>edge.id===edgeMenu.id)!,nodes),onSelect:()=>changeEdgeRole(edgeMenu.id,"relation")},
        {id:"delete",label:"删除连线",disabled:edgeLocked(edges.find(edge=>edge.id===edgeMenu.id)!,nodes),onSelect:()=>edit(nodesRef.current,edgesRef.current.filter(edge=>edge.id!==edgeMenu.id))},
      ]} />}
      {contextMenu && (
        <CanvasContextMenu
          position={contextMenu}
          items={menuItems}
          onClose={closeContextMenu}
        />
      )}
      {showDrafts && <DraftRecovery projectId={project.id} draftPrefix={draftPrefix} onClose={()=>setShowDrafts(false)} onRestore={restoreDraft}/>}
      {showProduction && <ProductionPanel projectId={project.id} onClose={()=>setShowProduction(false)} onChanged={()=>{void loadCanvas(false);void reloadAssets();onAssetsChange();}} onLocate={(id:string)=>{setShowProduction(false);locateNode(id);}}/>}
      {showCanvasRun && <CanvasRunPanel projectId={project.id} selectedNodeIds={selected.map(node=>node.id)} onClose={()=>setShowCanvasRun(false)} onChanged={()=>{void loadCanvas(false);void reloadAssets();onAssetsChange();}} onLocate={(id:string)=>{setShowCanvasRun(false);locateNode(id);}}/>}
      {showTimeline && <TimelineEditor projectId={project.id} onClose={()=>setShowTimeline(false)} onChanged={()=>{void loadCanvas(false);void reloadAssets();onAssetsChange();}}/>}
      {showLipSync && <LipSyncPanel projectId={project.id} initialVideoNodeId={lipSyncNodeId} onClose={()=>setShowLipSync(false)} onChanged={()=>{void loadCanvas(false);void reloadAssets();onAssetsChange();}}/>}
      {subjectDraft && (
        <SaveSubjectDialog
          snapshot={subjectDraft}
          projectId={project.id}
          canvasMedia={getCanvasMedia()}
          onClose={() => setSubjectDraft(null)}
          onSaved={(subject) => {
            setSubjectDraft(null);
            setSubjectRefresh((value) => value + 1);
            setShowLibrary(true);
            setAssetScope("subjects");
            setNotice(`已保存到主体库：${subject.name}`);
            onAssetsChange();
          }}
        />
      )}
      {saveSelection && (
        <SaveToCanvasDialog
          sourceProjectId={project.id}
          snapshot={saveSelection}
          onClose={() => setSaveSelection(null)}
          onSaved={(target) => {
            setSaveSelection(null);
            setNotice(`已保存到画布：${target.name}`);
          }}
        />
      )}
      <input
        ref={fileInput}
        type="file"
        multiple
        accept="image/*,video/*,audio/*"
        hidden
        onChange={(event) => {
          void importFiles(
            Array.from(event.target.files || []),
            importPosition.current,
          );
          importPosition.current = undefined;
          event.target.value = "";
        }}
      />
    </div>
  );
}
