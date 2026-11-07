import AudioWorkflow from "./AudioWorkflow";
import type {AudioProfile} from "./AudioWorkflow";
import StudioSelect from "./StudioSelect";
import VideoWorkflow from "./VideoWorkflow";
import OpenAIWorkflow from "./OpenAIWorkflow";
import type {VideoProfile} from "./videoProfile";
import {Film} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowDownToLine, ArrowUpRight, CheckCircle2, ChevronRight, CircuitBoard, Code2, Copy, FileJson, GitBranch, Image, LoaderCircle, Plus, RefreshCw, Save, Search, Settings2, SlidersHorizontal, Trash2, Upload, X } from "lucide-react";
import { api, dateText } from "./api";
import { Confirm, EmptyState, Modal } from "./ui";
import type { Workflow, WorkflowBinding, WorkflowBindings, WorkflowGraph, WorkflowMode, WorkflowReport } from "./workflowTypes";
import { workflowModeNames } from "./workflowTypes";
import "./workflows.css";

const modeIcons = { text_to_image: Image, reference: GitBranch, edit: SlidersHorizontal };
const mappingNames: Record<keyof WorkflowBindings, string> = { prompt: "中文描述", negative_prompt: "负面描述", seed: "随机种子", width: "输出宽度", height: "输出高度", steps: "采样步数", cfg: "提示词强度 CFG", denoise: "重绘强度", images: "参考图片（按顺序）", mask: "编辑蒙版" };
const parameterNames: Record<string, string> = { width: "宽度", height: "高度", steps: "步数", cfg: "CFG", denoise: "重绘强度", seed: "默认种子" };
const errorMessage = (error: unknown) => error instanceof Error ? error.message : String(error);
const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isNode = (value: unknown): value is WorkflowGraph[string] => isObject(value) && typeof value.class_type === "string" && !!value.class_type.trim() && isObject(value.inputs);
const graphEntries = (graph: unknown) => Object.entries(isObject(graph) ? graph : {}).filter((entry): entry is [string, WorkflowGraph[string]] => isNode(entry[1]));
const nodeLabel = (node: WorkflowGraph[string]) => typeof node._meta?.title === "string" ? node._meta.title : node.class_type;
const inputsFor = (graph: unknown, nodeId: string) => isObject(graph) && isNode(graph[nodeId]) ? Object.keys(graph[nodeId].inputs) : [];
function bindingRows(value: unknown): WorkflowBinding[] {
  return Array.isArray(value) ? value.map(item => ({ node_id: isObject(item) && typeof item.node_id === "string" ? item.node_id : "", input_name: isObject(item) && typeof item.input_name === "string" ? item.input_name : "" })) : [];
}
function parseGraph(value: unknown): WorkflowGraph {
  if (!isObject(value)) throw new Error("工作流 JSON 顶层须为节点对象，不能是 null、数组或文本。");
  if ("nodes" in value || "links" in value) throw new Error("这是 ComfyUI 画布文件，请从 ComfyUI 导出 API 格式的 JSON，再导入这里。");
  for (const [id, node] of Object.entries(value)) {
    if (!isNode(node)) throw new Error(`节点 ${id} 需要非空的 class_type 文本和 inputs 对象。JSON 内容已保留，可继续修正。`);
    for (const key of ["seed", "noise_seed"]) {
      if (typeof node.inputs[key] === "number" && !Number.isSafeInteger(node.inputs[key])) throw new Error(`节点 ${id} 的种子须为不超过 9007199254740991 的整数，以免导入时丢失精度。`);
    }
  }
  return value as WorkflowGraph;
}
function parseJson(text: string): unknown {
  try { return JSON.parse(text); } catch { throw new Error("JSON 格式不正确，请检查逗号、引号和括号。"); }
}
function importPayload(text: string) {
  const raw = parseJson(text);
  if (!isObject(raw)) throw new Error("工作流 JSON 顶层须为对象，不能是 null、数组或文本。");
  const wrapped = Object.hasOwn(raw, "api_graph");
  const graph = parseGraph(wrapped ? raw.api_graph : Object.hasOwn(raw, "prompt") ? raw.prompt : raw);
  if (isObject(raw.defaults) && typeof raw.defaults.seed === "number" && !Number.isSafeInteger(raw.defaults.seed)) throw new Error("默认种子须为不超过 9007199254740991 的整数。");
  return { raw, graph, wrapped };
}

function downloadWorkflow(workflow: Workflow) {
  const blob = new Blob([JSON.stringify({ format: "manju-workflow", version: 1, name: workflow.name, description: workflow.description, mode: workflow.mode, api_graph: workflow.api_graph, bindings: workflow.bindings, capabilities: workflow.capabilities, defaults: workflow.defaults, output_nodes: workflow.output_nodes }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${workflow.name.replace(/[<>:"/\\|?*]/g, "_")}.manju-workflow.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Workflows({ refresh, onChanged, onOpenComfy }: { refresh: number; onChanged: () => void; onOpenComfy: () => void }) {
  const [items, setItems] = useState<Workflow[]>([]);
  const [audio,setAudio]=useState<AudioProfile>(),[editingAudio,setEditingAudio]=useState(false);
  const [video,setVideo]=useState<VideoProfile>();
  const [editingVideo,setEditingVideo]=useState(false);
  const [editingOpenAI,setEditingOpenAI]=useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<WorkflowMode | "video" | "audio" | "all">("all");
  const [editing, setEditing] = useState<Workflow | null>(null);
  const [importing, setImporting] = useState(false);
  const [removing, setRemoving] = useState<Workflow | null>(null);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    let disposed = false;
    api<{items:(Workflow|VideoProfile|AudioProfile)[]}>("/api/workflows?include_video=true&include_audio=true").then(result => { if (!disposed) { setItems(result.items.filter(item=>!("kind" in item && (item.kind==="video"||item.kind==="audio"))) as Workflow[]); setVideo(result.items.find(item=>"kind" in item && item.kind==="video") as VideoProfile|undefined); setAudio(result.items.find(item=>"kind" in item && item.kind==="audio") as AudioProfile|undefined); setError(""); } }).catch(caught => { if (!disposed) setError(errorMessage(caught)); }).finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [refresh]);
  const open = async (id: string) => {
    if (id.startsWith("builtin-openai-")) { setEditingOpenAI(true); return; }
    setBusy(id);
    try { setEditing(await api<Workflow>(`/api/workflows/${id}`)); } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  };
  const duplicate = async (workflow: Workflow) => {
    setBusy(workflow.id);
    try { const result = await api<Workflow>(`/api/workflows/${workflow.id}/duplicate`, { method: "POST" }); setEditing(result); onChanged(); } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  };
  const validate = async (workflow: Workflow) => {
    setBusy(workflow.id);
    try {
      const result = await api<WorkflowReport>(`/api/workflows/${workflow.id}/validate`, { method: "POST" });
      setItems(current => current.map(item => item.id === workflow.id ? { ...item, validation: result, ready: result.valid && result.online } : item));
      setError("");
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); }
  };
  const filtered = items.filter(item => (mode === "all" || item.mode === mode) && `${item.name} ${item.description}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  const showAudio=(mode==="all"||mode==="audio")&&!!audio&&"indextts 2.5 人物配音 音色克隆 语音".includes(search.trim().toLocaleLowerCase());
  const showVideo=(mode==="all"||mode==="video")&&!!video&&"minimax h3 director 本地音视频 视频生成 文生视频 首尾帧 全参考".includes(search.trim().toLocaleLowerCase());
  return <div className="page workflows-page">
    <header className="page-heading"><div><span className="eyebrow">CONNECTED GENERATION</span><h1>工作流</h1><p>统一查看已接入的创作能力，管理本地流程与云端图片生成。</p></div><div className="workflow-heading-actions"><button className="button secondary" onClick={()=>setEditingOpenAI(true)}>OpenAI 连接与模型</button><button className="button secondary" onClick={onOpenComfy}><CircuitBoard size={16} />本地服务</button><button className="button primary" onClick={() => setImporting(true)}><Plus size={17} />导入工作流</button></div></header>
    <div className="workflow-intro"><div className="workflow-intro-icon"><GitBranch size={24} strokeWidth={1.5} /></div><div><strong>描述想法，连接参考，在原位生成</strong><p>统一管理图片、视频与人物配音工作流。选中画布卡片输入描述，用 @ 或连线传入素材，结果保留在当前卡片。</p></div><a className="workflow-intro-link" href="#/projects">前往项目<ArrowUpRight size={15} /></a></div>
    <div className="workflow-filterbar"><div className="workflow-mode-tabs">{(["all", "text_to_image", "reference", "edit", "video", "audio"] as const).map(key => <button key={key} className={mode === key ? "active" : ""} onClick={() => setMode(key)}>{key === "all" ? "全部工作流" : key === "video" ? "视频生成" : key === "audio" ? "人物配音" : workflowModeNames[key]}<span>{items.filter(item => key === "all" || item.mode === key).length+((key==="all"||key==="video")&&video?1:0)+((key==="all"||key==="audio")&&audio?1:0)}</span></button>)}</div><label className="workflow-search"><Search size={16} /><input aria-label="搜索工作流" placeholder="搜索名称或用途" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    {error && <div className="workflow-alert" role="alert"><AlertCircle size={17} /><span>{error}</span><button className="icon-button" title="重新读取工作流" onClick={onChanged}><RefreshCw size={15} /></button></div>}
    {loading ? <div className="loading"><LoaderCircle className="spin" size={22} />正在读取工作流</div> : filtered.length === 0 && !showVideo && !showAudio ? <EmptyState icon={<GitBranch />} title={items.length ? "没有匹配的工作流" : "添加你的第一条工作流"} description="可导入 ComfyUI 的 API 格式 JSON，在这里维护参数与图片输入映射。" action={<button className="button secondary" onClick={() => setImporting(true)}><Upload size={16} />导入 JSON</button>} /> : <div className="workflow-grid">{showVideo&&video&&<article className="workflow-card h3-library-card">
      <button className="workflow-card-main" onClick={()=>setEditingVideo(true)}><div className="workflow-card-icon"><Film size={25}/></div><div className="workflow-card-tags"><span>视频生成</span><span className="builtin">内置</span></div><h2>MiniMax H3 · 本地音视频</h2><p>原生基线与 Director 镜头组统一管理。支持文生、首尾帧与全参考；可裁切人物参考、选择片段及是否带入原声。</p><div className="workflow-card-capabilities"><span>3 种模式</span><span>4–15 秒</span><span>原生音视频</span></div></button>
      <div className="workflow-card-validation"><span className={video.ready?"ready":"invalid"}>{video.ready?<CheckCircle2 size={13}/>:<AlertCircle size={13}/>} {video.ready?"本机可用":`${video.errors.length} 项需要处理`}</span><button disabled={busy==="video"} onClick={async()=>{setBusy("video");try{setVideo(await api<VideoProfile>("/api/video/settings"));}catch(e){setError(errorMessage(e));}finally{setBusy("");}}}><RefreshCw size={13}/>检查</button></div>
      <footer><span>共享配置 · 修订 {video.revision}</span><button className="workflow-open" onClick={()=>setEditingVideo(true)}>管理<ChevronRight size={14}/></button></footer>
    </article>}{showAudio&&audio&&<article className="workflow-card"><button className="workflow-card-main" onClick={()=>setEditingAudio(true)}><div className="workflow-card-icon"><SlidersHorizontal size={25}/></div><div className="workflow-card-tags"><span>人物配音</span><span className="builtin">本地</span></div><h2>{audio.name}</h2><p>用主体绑定的参考音频克隆人物音色，支持中文台词、语速与情绪控制。与图片、视频共用生成队列及原卡片历史。</p><div className="workflow-card-capabilities"><span>单人音色参考</span><span>5 种语言</span><span>无损音频</span></div></button><div className="workflow-card-validation"><span className={audio.ready?'ready':'invalid'}>{audio.ready?'本机可用':`${audio.errors.length} 项需要处理`}</span><button onClick={()=>setEditingAudio(true)}>检查</button></div><footer><span>共享配置 · 修订 {audio.revision}</span><button onClick={()=>setEditingAudio(true)}>管理<ChevronRight size={14}/></button></footer></article>}{filtered.map(workflow => {
      const Icon = modeIcons[workflow.mode];
      const report = workflow.validation;
      return <article className="workflow-card" key={workflow.id}>
        <button className="workflow-card-main" onClick={() => void open(workflow.id)} disabled={busy === workflow.id}>
          <div className={`workflow-card-icon ${workflow.mode}`}><Icon size={25} strokeWidth={1.5} /></div><div className="workflow-card-tags"><span>{workflowModeNames[workflow.mode]}</span>{workflow.provider==="openai"?<span className="cloud">OpenAI 云端</span>:workflow.builtin && <span className="builtin">内置</span>}</div>
          <h2>{workflow.name}</h2><p>{workflow.description || "自定义 ComfyUI 工作流"}</p>
          <div className="workflow-card-capabilities">{workflow.capabilities.max_images > 0 ? <span><Image size={12} />{workflow.capabilities.min_images}–{workflow.capabilities.max_images} 张参考图</span> : <span>从文字开始创作</span>}{workflow.capabilities.supports_mask && <span>蒙版编辑</span>}</div>
        </button>
        <div className="workflow-card-validation"><span className={workflow.ready ? "ready" : report?.errors.length ? "invalid" : "unchecked"}>{workflow.ready ? <CheckCircle2 size={13} /> : report?.errors.length ? <AlertCircle size={13} /> : <span className="workflow-status-dot" />}{workflow.provider==="openai"?(report?.valid?"连接检查通过":report?"连接需要检查":workflow.ready?"密钥已配置 · 可检查连接":"尚未配置密钥"):workflow.ready ? "本机可用" : report ? !report.online ? "等待 ComfyUI 服务" : `${report.errors.length} 项需要处理` : "尚未检查本机环境"}</span><button onClick={() => void validate(workflow)} disabled={busy === workflow.id}>{busy === workflow.id ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}检查</button></div>
        <footer><span>{workflow.provider==="openai"?"按用量计费 · 生成前预估":`更新于 ${dateText(workflow.updated_at)}`}</span><div>{workflow.provider!=="openai"&&<><button title="导出工作流" onClick={() => downloadWorkflow(workflow)}><ArrowDownToLine size={15} /></button><button title="复制工作流" onClick={() => void duplicate(workflow)} disabled={!!busy}><Copy size={15} /></button>{!workflow.read_only && <button title="删除工作流" onClick={() => setRemoving(workflow)}><Trash2 size={15} /></button>}</>}<button className="workflow-open" onClick={() => void open(workflow.id)}>查看<ChevronRight size={14} /></button></div></footer>
      </article>;
    })}</div>}
    <div className="workflow-library-note"><FileJson size={15} /><span>本地 ComfyUI、H3 与 OpenAI 云端能力共用此入口。OpenAI 支持模型与费用查询；本地图片模板可复制、导入，H3 可管理模型与默认参数。</span></div>
    {editingAudio&&<AudioWorkflow onClose={()=>setEditingAudio(false)} onSaved={setAudio}/>}
    {editingOpenAI&&<OpenAIWorkflow onClose={()=>setEditingOpenAI(false)}/>}
    {editingVideo&&<VideoWorkflow onClose={()=>setEditingVideo(false)} onSaved={setVideo}/>}
    {editing && <WorkflowEditor workflow={editing} onClose={() => setEditing(null)} onSaved={workflow => { setEditing(workflow); onChanged(); }} onDuplicate={() => void duplicate(editing)} onOpenComfy={onOpenComfy} />}
    {importing && <WorkflowImport onClose={() => setImporting(false)} onImported={workflow => { setImporting(false); setEditing(workflow); onChanged(); }} />}
    {removing && <Confirm title="删除这条工作流？" description={`“${removing.name}”将不再出现在画布工作流列表中，已经生成的资产和任务记录会保留。`} busy={busy === removing.id} onClose={() => setRemoving(null)} onConfirm={async () => { setBusy(removing.id); try { await api(`/api/workflows/${removing.id}`, { method: "DELETE" }); setRemoving(null); onChanged(); } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(""); } }} />}
  </div>;
}

function WorkflowEditor({ workflow, onClose, onSaved, onDuplicate, onOpenComfy }: { workflow: Workflow; onClose: () => void; onSaved: (workflow: Workflow) => void; onDuplicate: () => void; onOpenComfy: () => void }) {
  const [draft, setDraft] = useState<Workflow>(workflow);
  const [jsonText, setJsonText] = useState(JSON.stringify(workflow.api_graph, null, 2));
  const [tab, setTab] = useState<"settings" | "bindings" | "json" | "validation">("settings");
  const [dirty, setDirty] = useState(false);
  const [jsonDirty, setJsonDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState(workflow.validation);
  const dialogContent = useRef<HTMLDivElement>(null);
  useEffect(() => { setDraft(workflow); setJsonText(JSON.stringify(workflow.api_graph, null, 2)); setDirty(false); setJsonDirty(false); setReport(workflow.validation); setError(""); }, [workflow]);
  useEffect(() => { const dialog = dialogContent.current?.closest<HTMLElement>("[role=dialog]"); dialog?.focus(); }, []);
  const patch = (changes: Partial<Workflow>) => { setDraft(current => ({ ...current, ...changes })); if (changes.api_graph) { setJsonText(JSON.stringify(changes.api_graph, null, 2)); setJsonDirty(false); } setDirty(true); setReport(null); setError(""); };
  const applyJson = () => { try { patch({ api_graph: parseGraph(parseJson(jsonText)) }); } catch (caught) { setError(errorMessage(caught)); } };
  const exportDraft = () => { try { downloadWorkflow({ ...draft, api_graph: parseGraph(parseJson(jsonText)) }); } catch (caught) { setError(errorMessage(caught)); setTab("json"); } };
  const close = () => { if (!dirty || window.confirm("有尚未保存的工作流修改，确定关闭？")) onClose(); };
  const save = async () => {
    setBusy(true); setError("");
    try {
      const graph = parseGraph(parseJson(jsonText));
      if (typeof draft.defaults.seed === "number" && !Number.isSafeInteger(draft.defaults.seed)) throw new Error("默认种子须为不超过 9007199254740991 的整数。");
      const result = await api<Workflow>(`/api/workflows/${workflow.id}`, { method: "PUT", body: JSON.stringify({ ...draft, api_graph: graph, revision: workflow.revision }) });
      setDirty(false); onSaved(result);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  };
  const check = async () => {
    setBusy(true); setError("");
    try { setReport(await api<WorkflowReport>(`/api/workflows/${workflow.id}/validate`, { method: "POST" })); setTab("validation"); } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  };
  const updateBinding = (key: keyof WorkflowBindings, values: WorkflowBinding[]) => patch({ bindings: { ...draft.bindings, [key]: key === "mask" ? values[0] || null : values } });
  const nodes = graphEntries(draft.api_graph);
  const outputs = Array.isArray(draft.output_nodes) ? draft.output_nodes.filter(value => typeof value === "string") : [];
  const models = nodes.flatMap(([id, node]) => Object.entries(node.inputs).filter(([key, value]) => typeof value === "string" && /^(ckpt|unet|clip|vae|lora|model)_name$/.test(key)).map(([key, value]) => ({ id, node, key, value: value as string })));
  let graphError = "";
  try { parseGraph(draft.api_graph); } catch (caught) { graphError = errorMessage(caught); }
  return <Modal title={workflow.name} onClose={close} wide className="management-modal workflow-modal"><div className="workflow-editor" ref={dialogContent}>
    <div className="workflow-editor-heading"><span className="workflow-mode-label">{workflowModeNames[draft.mode]}</span><span>{Object.keys(isObject(draft.api_graph) ? draft.api_graph : {}).length} 个节点 · 修订 {workflow.revision}</span>{workflow.read_only && <span className="workflow-readonly">内置模板</span>}<button className="workflow-text-button" onClick={exportDraft}><ArrowDownToLine size={14} />导出 JSON</button></div>
    {workflow.read_only && <div className="workflow-readonly-note"><Copy size={15} /><span>先复制为自己的工作流，即可修改模型、参数和输入映射。</span><button onClick={onDuplicate}>复制并编辑<ChevronRight size={14} /></button></div>}
    <div className="workflow-editor-tabs">{([['settings', '基础与参数', Settings2], ['bindings', '输入与输出', GitBranch], ['json', '工作流 JSON', Code2], ['validation', '环境检查', CheckCircle2]] as const).map(([key, label, Icon]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}><Icon size={15} />{label}</button>)}</div>
    {error && <div className="workflow-alert" role="alert"><AlertCircle size={16} />{error}</div>}
    {graphError && <div className="workflow-alert" role="alert"><AlertCircle size={16} /><span>{graphError}</span><button className="workflow-text-button" onClick={() => setTab("json")}>修正 JSON</button></div>}
    {jsonDirty && tab !== "json" && <div className="workflow-json-pending"><Code2 size={15} /><span>JSON 修改尚未应用，模型表单暂时锁定。</span><button onClick={applyJson}>应用修改</button><button onClick={() => setTab("json")}>查看 JSON</button></div>}
    <div className="workflow-editor-body">
      {tab === "settings" && <div className="workflow-settings-grid"><section><h3>工作流信息</h3><label>名称<input value={draft.name} disabled={workflow.read_only} onChange={event => patch({ name: event.target.value })} /></label><label>用途<StudioSelect value={draft.mode} disabled={workflow.read_only} onChange={event => patch({ mode: event.target.value as WorkflowMode })}>{Object.entries(workflowModeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</StudioSelect></label><label>使用说明<textarea rows={4} value={draft.description} disabled={workflow.read_only} onChange={event => patch({ description: event.target.value })} /></label><h3>模型配置</h3>{models.length ? models.map(model => <label key={`${model.id}.${model.key}`}><span>{nodeLabel(model.node)}<small>节点 {model.id} · {model.key}</small></span><input disabled={workflow.read_only || jsonDirty} value={model.value} onChange={event => patch({ api_graph: { ...draft.api_graph, [model.id]: { ...model.node, inputs: { ...model.node.inputs, [model.key]: event.target.value } } } })} /></label>) : <p className="workflow-muted">可在 JSON 中编辑此工作流的模型输入。</p>}</section><section><h3>画布中的默认参数</h3><div className="workflow-defaults-grid">{Object.entries(parameterNames).map(([key, name]) => <label key={key}>{name}<input type="number" step={key === "cfg" || key === "denoise" ? "0.05" : "1"} disabled={workflow.read_only} value={draft.defaults[key] ?? ""} onChange={event => patch({ defaults: { ...draft.defaults, [key]: event.target.value === "" ? "" : Number(event.target.value) } })} /></label>)}</div><label>负面描述<textarea rows={3} disabled={workflow.read_only} value={draft.defaults.negative_prompt || ""} onChange={event => patch({ defaults: { ...draft.defaults, negative_prompt: event.target.value } })} /></label><h3>图片输入能力</h3><div className="workflow-defaults-grid"><label>最少参考图<input type="number" min={0} max={10} disabled={workflow.read_only} value={draft.capabilities.min_images} onChange={event => patch({ capabilities: { ...draft.capabilities, min_images: Number(event.target.value) } })} /></label><label>最多参考图<input type="number" min={0} max={10} disabled={workflow.read_only} value={draft.capabilities.max_images} onChange={event => patch({ capabilities: { ...draft.capabilities, max_images: Number(event.target.value) } })} /></label></div><label>主体名称映射<StudioSelect disabled={workflow.read_only} value={draft.capabilities.reference_mapping || (workflow.id.startsWith("builtin-qwen21-")?"numbered":"unsupported")} onChange={event=>patch({capabilities:{...draft.capabilities,reference_mapping:event.target.value as "numbered"|"unsupported"}})}><option value="unsupported">未适配（保留普通图片输入）</option><option value="numbered">按参考图编号映射名称（须模型支持）</option></StudioSelect></label><label>图片处理方式<StudioSelect disabled={workflow.read_only} value={draft.capabilities.reference_kind} onChange={event => patch({ capabilities: { ...draft.capabilities, reference_kind: event.target.value as Workflow['capabilities']['reference_kind'] } })}><option value="none">没有图片输入</option><option value="image_conditioning">图像条件参考</option><option value="img2img">图生图重绘</option></StudioSelect></label><div className="workflow-checkboxes"><label><input type="checkbox" checked={draft.capabilities.supports_mask} disabled={workflow.read_only} onChange={event => patch({ capabilities: { ...draft.capabilities, supports_mask: event.target.checked, requires_mask: event.target.checked && draft.capabilities.requires_mask } })} />支持蒙版</label><label><input type="checkbox" checked={draft.capabilities.requires_mask} disabled={workflow.read_only || !draft.capabilities.supports_mask} onChange={event => patch({ capabilities: { ...draft.capabilities, requires_mask: event.target.checked } })} />必须提供蒙版</label></div><p className="workflow-muted">能力声明须与输入映射、实际节点一致。环境检查会指出无法执行的配置。</p></section></div>}
      {tab === "bindings" && <div className="workflow-bindings"><div className="workflow-binding-guide"><GitBranch size={18} /><p>将画布里的描述和图片接到实际节点输入。多张参考图按列表顺序送入；工作流中的连线仍由 JSON 保留。</p></div>{Object.keys(mappingNames).map(value => {
        const key = value as keyof WorkflowBindings;
        const mapped = bindingRows(key === "mask" ? draft.bindings?.mask ? [draft.bindings.mask] : [] : draft.bindings?.[key]);
        return <section className="workflow-binding-group" key={key}><div><h4>{mappingNames[key]}</h4><span>{key === "images" ? "上传后将文件名填入 LoadImage 等输入" : key === "mask" ? "白色区域编辑，黑色区域保留" : "可同时绑定到多个节点"}</span></div><div className="workflow-binding-rows">{mapped.map((binding, index) => <div className="workflow-binding-row" key={index}><span>{key === "images" ? `图 ${index + 1}` : index + 1}</span><StudioSelect aria-label={`${mappingNames[key]}节点${index + 1}`} value={binding.node_id} disabled={workflow.read_only} onChange={event => { const nodeId = event.target.value; updateBinding(key, mapped.map((item, i) => i === index ? { node_id: nodeId, input_name: inputsFor(draft.api_graph, nodeId)[0] || "" } : item)); }}><option value="">选择节点</option>{nodes.map(([id, node]) => <option key={id} value={id}>{id} · {nodeLabel(node)}</option>)}</StudioSelect><ChevronRight size={13} /><StudioSelect aria-label={`${mappingNames[key]}输入${index + 1}`} value={binding.input_name} disabled={workflow.read_only} onChange={event => updateBinding(key, mapped.map((item, i) => i === index ? { ...item, input_name: event.target.value } : item))}><option value="">选择输入</option>{inputsFor(draft.api_graph, binding.node_id).map(input => <option key={input}>{input}</option>)}</StudioSelect>{!workflow.read_only && <button title="移除映射" onClick={() => updateBinding(key, mapped.filter((_, i) => i !== index))}><X size={14} /></button>}</div>)}{!workflow.read_only && (key !== "mask" || mapped.length === 0) && <button className="workflow-add-binding" onClick={() => updateBinding(key, [...mapped, { node_id: "", input_name: "" }])}><Plus size={13} />添加映射</button>}{workflow.read_only && mapped.length === 0 && <span className="workflow-muted">未使用</span>}</div></section>;
      })}<section className="workflow-binding-group"><div><h4>结果输出节点</h4><span>仅收集选定节点产生的图片</span></div><div className="workflow-output-options">{nodes.filter(([id, node]) => node.class_type === "SaveImage" || outputs.includes(id)).map(([id, node]) => <label key={id}><input type="checkbox" checked={outputs.includes(id)} disabled={workflow.read_only} onChange={event => patch({ output_nodes: event.target.checked ? [...outputs, id] : outputs.filter(value => value !== id) })} />{id} · {nodeLabel(node)}</label>)}</div></section></div>}
      {tab === "json" && <div className="workflow-json-panel"><p>ComfyUI API 格式：每个节点包含 class_type 和 inputs。保存后请重新检查节点和模型是否可用。</p><textarea aria-label="工作流 API JSON" spellCheck={false} value={jsonText} readOnly={workflow.read_only} onChange={event => { setJsonText(event.target.value); setJsonDirty(true); setDirty(true); setReport(null); setError(""); }} /><button className="button secondary small" disabled={workflow.read_only} onClick={applyJson}>应用 JSON 到输入映射</button></div>}
      {tab === "validation" && <div className="workflow-validation"><div className={`workflow-validation-hero ${report?.valid && report.online ? "valid" : ""}`}>{report?.valid && report.online ? <CheckCircle2 size={30} /> : <CircuitBoard size={30} />}<h3>{!report ? "检查本机运行环境" : report.valid && report.online ? "工作流已准备好" : !report.online ? "需要连接 ComfyUI" : "还有配置需要处理"}</h3><p>{report ? `检查时间：${new Date(report.checked_at).toLocaleString("zh-CN")}` : "检查模型文件、节点类型，以及描述和图片是否连通到输出。"}</p><button className="button secondary" onClick={onOpenComfy}><CircuitBoard size={15} />管理本地服务</button></div>{report && [...report.errors.map(issue => ({ ...issue, kind: "error" })), ...report.warnings.map(issue => ({ ...issue, kind: "warning" }))].map((issue, index) => <div className={`workflow-validation-issue ${issue.kind}`} key={index}><AlertCircle size={17} /><div><strong>{issue.message}</strong>{issue.node_id && <span>节点 {issue.node_id}{issue.input_name ? ` · ${issue.input_name}` : ""}</span>}</div></div>)}</div>}
    </div>
    <footer className="workflow-editor-footer"><span>{dirty ? "有未保存的修改" : workflow.read_only ? "内置模板" : "已保存到本机"}</span><button className="button secondary" onClick={check} disabled={busy || dirty}>{busy ? <LoaderCircle className="spin" size={15} /> : <CheckCircle2 size={15} />}检查可用性</button>{!workflow.read_only && <button className="button primary" onClick={save} disabled={busy || !dirty}>{busy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />}保存工作流</button>}<button className="button secondary" onClick={close}>关闭</button></footer>
  </div></Modal>;
}

function WorkflowImport({ onClose, onImported }: { onClose: () => void; onImported: (workflow: Workflow) => void }) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<WorkflowMode>("text_to_image");
  const [jsonText, setJsonText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filename, setFilename] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const importFile = async (selected?: File) => {
    if (!selected) return;
    if (selected.size > 5 * 1024 * 1024) { setError("工作流 JSON 最大支持 5 MB。"); return; }
    try {
      const text = await selected.text();
      setJsonText(text); setFilename(selected.name);
      const { raw } = importPayload(text);
      setName(typeof raw.name === "string" ? raw.name : selected.name.replace(/\.(manju-workflow\.)?json$/i, ""));
      if (typeof raw.mode === "string" && Object.hasOwn(workflowModeNames, raw.mode)) setMode(raw.mode as WorkflowMode);
      setError("");
    } catch (caught) { setError(errorMessage(caught)); }
  };
  const submit = async () => {
    setBusy(true); setError("");
    try {
      const { raw, graph, wrapped } = importPayload(jsonText);
      const result = await api<Workflow>("/api/workflows/import", { method: "POST", body: JSON.stringify({ name: name.trim() || "导入的工作流", mode, api_graph: graph, ...(wrapped ? { description: raw.description, bindings: raw.bindings, capabilities: raw.capabilities, defaults: raw.defaults, output_nodes: raw.output_nodes } : {}) }) });
      onImported(result);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  };
  return <Modal title="导入工作流" onClose={onClose}><div className="workflow-import"><input ref={file} type="file" accept=".json,application/json" hidden onChange={event => { void importFile(event.target.files?.[0]); event.target.value = ""; }} /><button className="workflow-file-drop" onClick={() => file.current?.click()} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); void importFile(event.dataTransfer.files[0]); }}><FileJson size={29} strokeWidth={1.4} /><strong>{filename || "选择或拖入 JSON 文件"}</strong><span>ComfyUI API 格式，或工作台导出的工作流</span></button><label>工作流名称<input autoFocus value={name} onChange={event => setName(event.target.value)} placeholder="例如：角色参考图 · Qwen" /></label><label>用途<StudioSelect value={mode} onChange={event => setMode(event.target.value as WorkflowMode)}>{Object.entries(workflowModeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</StudioSelect></label><details open={!filename || !!error}><summary>也可以粘贴 API JSON</summary><textarea aria-label="粘贴工作流 JSON" rows={7} spellCheck={false} value={jsonText} onChange={event => setJsonText(event.target.value)} placeholder={'{ "1": { "class_type": "...", "inputs": {} } }'} /></details>{error && <div className="workflow-alert" role="alert"><AlertCircle size={16} />{error}</div>}<p className="workflow-muted">导入后会自动识别常用输入。请检查描述、图片和输出的映射，再检查本机可用性。</p></div><footer className="modal-footer"><button className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={busy || !jsonText.trim()} onClick={submit}>{busy ? <LoaderCircle size={16} className="spin" /> : <Upload size={16} />}导入并配置</button></footer></Modal>;
}
