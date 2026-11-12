import {useEffect,useState} from "react";
import {createPortal} from "react-dom";
import "./workflows.css";
import {AlertCircle,ArrowDownToLine,CheckCircle2,Film,LoaderCircle,RefreshCw,Save,Settings2} from "lucide-react";
import {api} from "./api";
import {Modal} from "./ui";
import StudioSelect from "./StudioSelect";
import {videoModelMatches,videoModelNames,videoModeNames,videoEngines} from "./videoProfile";
import type {VideoEngine} from "./generationTypes";
import type {VideoDefaults,VideoProfile} from "./videoProfile";
type Mode=keyof typeof videoModeNames;
type Template={api_graph:Record<string,unknown>;revision:number;placeholder_files:string[]};
const message=(e:unknown)=>e instanceof Error?e.message:String(e);
export default function VideoWorkflow({onClose,onSaved,initialEngine="native"}:{initialEngine?:VideoEngine;onClose:()=>void;onSaved?:(profile:VideoProfile)=>void}){
  const [profile,setProfile]=useState<VideoProfile>(),[models,setModels]=useState<Record<string,string>>({}),[defaults,setDefaults]=useState<VideoDefaults>();
  const [dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(""),[feedback,setFeedback]=useState("");
  const [engine,setEngine]=useState<VideoEngine>(initialEngine);
  const [tab,setTab]=useState<"settings"|"graph">("settings"),[mode,setMode]=useState<Mode>(initialEngine==="turbo"?"reference":"text"),[graph,setGraph]=useState<Template>(),[graphError,setGraphError]=useState("");
  function apply(value:VideoProfile){setProfile(value);setModels(value.models);setDefaults(value.defaults);setDirty(false);onSaved?.(value);}
  useEffect(()=>{let alive=true;api<VideoProfile>("/api/video/settings").then(value=>{if(alive){setProfile(value);setModels(value.models);setDefaults(value.defaults);}}).catch(e=>{if(alive)setError(message(e));});return()=>{alive=false;};},[]);
  useEffect(()=>{if(tab!=="graph"||!profile)return;let alive=true;setGraph(undefined);setGraphError("");api<Template>(`/api/video/workflow?mode=${mode}&engine=${engine}`).then(value=>{if(alive)setGraph(value);}).catch(e=>{if(alive)setGraphError(message(e));});return()=>{alive=false;};},[tab,mode,engine,profile?.revision]);
  function close(){if(!busy&&(!dirty||window.confirm("有未保存的 H3 配置，确定关闭？")))onClose();}
  async function refresh(){if(dirty&&!window.confirm("重新读取将放弃尚未保存的配置，是否继续？"))return;setBusy(true);setError("");setFeedback("");try{apply(await api<VideoProfile>("/api/video/settings"));}catch(e){setError(message(e));}finally{setBusy(false);}}
  async function save(){if(!profile||!defaults)return;setBusy(true);setError("");setFeedback("");try{apply(await api<VideoProfile>("/api/video/settings",{method:"PUT",body:JSON.stringify({revision:profile.revision,models,defaults})}));setFeedback("配置已保存。新建视频卡使用这些默认参数，已有卡片保留原参数。");}catch(e){setError(message(e));}finally{setBusy(false);}}
  function exportGraph(){if(!graph)return;const url=URL.createObjectURL(new Blob([JSON.stringify(graph.api_graph,null,2)],{type:"application/json"}));const link=document.createElement("a");link.href=url;link.download=`MiniMax-H3-${engine}-${mode}.api.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  return createPortal(<Modal title="MiniMax H3 · 本地音视频" onClose={close} wide className="management-modal workflow-modal h3-workflow-modal">
    <div className="workflow-editor">
      <div className="workflow-editor-heading"><span className="workflow-mode-label">视频生成</span><span>内置动态工作流{profile?` · 修订 ${profile.revision}`:""}</span><span className={profile?.ready?"h3-ready":""}>{profile?(profile.ready?"本机可用":"需要配置环境"):"读取中…"}</span></div>
      <div className="workflow-editor-tabs"><button className={tab==="settings"?"active":""} onClick={()=>setTab("settings")}><Settings2 size={16}/>模型与默认参数</button><button className={tab==="graph"?"active":""} onClick={()=>setTab("graph")}><Film size={16}/>流程与输入</button></div>
      <div className="workflow-editor-body">
        {error&&<div className="workflow-alert" role="alert"><AlertCircle size={16}/>{error}</div>}
        {feedback&&<p role="status" className="h3-feedback">{feedback}</p>}
        {!profile?<div className="loading"><LoaderCircle className="spin" size={20}/>正在读取本地配置</div>:tab==="settings"?<>
          <div className="h3-workflow-note">画布与工作流库共用这一份配置。支持原生基线、Director 外接镜头组和 Turbo 8 步全能参考，均在原卡片返回候选结果。模型用于后续提交的任务；默认参数用于新建视频卡，已有任务保留自己的配置快照。</div>
          <div className="workflow-settings-grid"><section><h3>本地模型</h3>{Object.entries(videoModelNames).map(([key,label])=>{
            const options=(profile.catalog[key]||[]).filter(value=>videoModelMatches(key,value));
            return <label key={key}>{label}<StudioSelect aria-label={label} value={models[key]||""} disabled={busy} onChange={e=>{setModels({...models,[key]:e.target.value});setDirty(true);setFeedback("");}}><option value="">请选择本地模型</option>{models[key]&&!options.includes(models[key])&&<option value={models[key]}>{models[key]}（当前不可用）</option>}{options.map(value=><option key={value}>{value}</option>)}</StudioSelect></label>;
          })}<p className="workflow-muted">模型列表来自本机 ComfyUI。停止服务后仍可查看已保存配置，重新连接后可检查环境。</p></section>
          <section><h3>新建视频卡的默认参数</h3>{defaults&&<><div className="workflow-defaults-grid">{([['width','宽度',256,1344,32],['height','高度',256,1344,32],['steps','采样步数',1,100,1],['cfg','CFG',0,20,.5],['seed','种子（-1 随机）',-1,9007199254740991,1],['duration','时长（秒）',4,15,1]] as const).map(([key,label,min,max,step])=><label key={key}>{label}<input aria-label={`默认${label}`} type="number" min={min} max={max} step={step} disabled={busy} value={Number.isFinite(defaults[key])?defaults[key]:""} onChange={e=>{setDefaults({...defaults,[key]:e.target.value===""?NaN:Number(e.target.value)});setDirty(true);setFeedback("");}}/></label>)}</div><label className="h3-audio-option"><input type="checkbox" checked={defaults.audio} disabled={busy} onChange={e=>{setDefaults({...defaults,audio:e.target.checked});setDirty(true);setFeedback("");}}/>生成声音</label></>}<p className="workflow-muted">尺寸须为 32 的倍数，范围 256–1344，总像素不超过 1344 × 768。24 fps，实际时长会按模型帧数要求对齐。</p></section></div>
          <section className="h3-environment"><h3>环境检查</h3><p>推荐采样：res_multistep / simple · CFG 1 · 20 步；参考图默认独立按 1024 处理。已有卡片可在创作设置中恢复推荐采样。</p><p>Director：{profile.engines?.director?.ready?"已安装，可从画布视频模型菜单选择":profile.engines?.director?.errors.join("；")||"尚未检测"}</p><p>Turbo 8 步：{profile.engines?.turbo?.ready?"已安装，可从画布视频模型菜单选择":profile.engines?.turbo?.errors.join("；")||"尚未检测"}</p>{profile.ready?<p className="h3-ready"><CheckCircle2 size={16}/>所需节点和模型已找到</p>:profile.errors.map((item,i)=><p key={i}><AlertCircle size={15}/>{item}</p>)}</section>
        </>:<>
          <div className="h3-flow-toolbar"><label>执行流程<StudioSelect aria-label="查看执行流程" value={engine} onChange={e=>{const next=e.target.value as VideoEngine;setEngine(next);if(next==="turbo")setMode("reference");}}>{Object.entries(videoEngines).map(([key,value])=><option key={key} value={key}>{value.label}</option>)}</StudioSelect></label><label>生成方式<StudioSelect aria-label="查看视频流程" disabled={engine==="turbo"} value={mode} onChange={e=>setMode(e.target.value as Mode)}>{Object.entries(videoModeNames).map(([key,label])=><option key={key} value={key}>{label}</option>)}</StudioSelect></label><button className="button secondary" disabled={!graph||dirty} onClick={exportGraph}><ArrowDownToLine size={16}/>导出 API 模板</button></div>
          <div className="h3-workflow-note">{mode==="text"?"输入文字描述，生成带声音的视频。":mode==="frames"?"首帧、尾帧分别最多一张图片，可仅提供其中一帧。":"最多 9 张图片、3 段视频、3 段音频，合计最多 12 个；视频、音频每段 2–15 秒，各类合计不超过 15 秒。"} 使用画布上的 @ 或连线传入素材。</div>
          <div className="h3-flow-steps"><span>描述 / 参考素材</span><b>→</b><span>H3 条件编码</span><b>→</b><span>音视频采样</span><b>→</b><span>解码 · MP4</span></div>
          <p className="workflow-muted">Director 以一张画布卡对应一个外接镜头组，当前不自动编排多镜头。以下模板由实际生成所用的同一编译器构建，展示已保存的配置。参考文件名为占位符，导入 ComfyUI 后需替换；实际任务会填入上传文件和随机种子。本工作台暂不支持导入、复制任意视频 JSON 为新生成器。</p>
          {dirty&&<p className="workflow-alert">配置尚未保存，保存后再查看或导出更新后的模板。</p>}
          {graphError?<div className="workflow-alert" role="alert">{graphError}</div>:graph?<textarea className="h3-graph" aria-label="H3 工作流 API JSON" readOnly value={JSON.stringify(graph.api_graph,null,2)}/>:<div className="loading">正在构建流程预览…</div>}
        </>}
      </div>
      <footer className="workflow-editor-footer"><span>{dirty?"有未保存的配置":"与画布视频创作共用配置"}</span><button className="button secondary" disabled={busy} onClick={()=>void refresh()}><RefreshCw size={15}/>重新读取 / 检查</button><button className="button primary" disabled={busy||!dirty||!defaults||Object.values(defaults).some(value=>typeof value==="number"&&!Number.isFinite(value))} onClick={()=>void save()}>{busy?<LoaderCircle className="spin" size={15}/>:<Save size={15}/>}保存配置</button><button className="button secondary" disabled={busy} onClick={close}>关闭</button></footer>
    </div>
  </Modal>,document.body);
}
