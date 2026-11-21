import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, mediaUrl } from "./api";
import { useLayer } from "./shell/layers";

type Step = {node_id:string; title:string; label?:string; kind:string; dependencies:string[]; action?:string; reason?:string; status?:string; error?:string; job_id?:string; job_status?:string; job_progress?:number|null; message?:string; output_version_id?:string};
type Plan = {revision:number; nodes:Step[]; valid:boolean; errors:{node_id?:string;message:string}[]; warnings:{message:string}[]};
type Run = {id:string; status:string; nodes:Step[]; progress:number; created_at:string};
type Props = {projectId:string; selectedNodeIds:string[]; onClose:()=>void; onChanged:()=>void; onLocate:(id:string)=>void};
const active = (run?:Run) => !!run && ["pending","running","cancelling"].includes(run.status);
const labels:Record<string,string> = {pending:"等待依赖",submitting:"正在提交",running:"生成中",succeeded:"完成",reused:"复用固定版本",failed:"失败",blocked:"上游失败，未提交",cancelled:"已取消",cancelling:"停止后续，等待当前任务",generate:"生成",reuse:"复用"};
const message = (error:unknown) => error instanceof Error ? error.message : String(error);

export default function CanvasRunPanel({projectId,selectedNodeIds,onClose,onChanged,onLocate}:Props) {
  // Shared layer stack: Esc closes it (one layer at a time) and focus goes back to the control that
  // opened it, or to 更多 when that was a menu item. Closing never stops a submitted run.
  const dialog = useRef<HTMLElement>(null);
  const isTop = useLayer(true, onClose, { ref: dialog, fallback: "[aria-label=\"更多画布选项\"]" });
  useEffect(() => {
    dialog.current?.focus({ preventScroll: true });
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialog.current || !isTop()) return;
      const items = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]")).filter(element => element.getClientRects().length > 0);
      const first = items[0], last = items[items.length - 1];
      if (!dialog.current.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first || document.activeElement === dialog.current : document.activeElement === last)) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => document.removeEventListener("keydown", trap);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- mount only
  }, []);
  const [scope,setScope] = useState<"all"|"downstream">(selectedNodeIds.length ? "downstream" : "all"), [force,setForce] = useState(false);
  const [plan,setPlan] = useState<Plan>(), [run,setRun] = useState<Run>(), [history,setHistory] = useState<Run[]>([]);
  const [busy,setBusy] = useState(""), [error,setError] = useState("");
  const alive=useRef(true),changed=useRef(onChanged),seen=useRef(new Set<string>());
  changed.current=onChanged;
  const base=`/api/projects/${encodeURIComponent(projectId)}/canvas-runs`, key=`manju:canvas-run-request:${projectId}`;
  const request = useRef<{fingerprint:string;id:string}|undefined>(undefined);
  async function loadHistory() {
    const result=await api<Run[]|{items:Run[]}>(base),items=Array.isArray(result)?result:result.items;
    if(alive.current){setHistory(items);setRun(current=>current||items.find(active)||items[0]);}
  }
  useEffect(()=>{
    alive.current=true;
    try { const saved=JSON.parse(localStorage.getItem(key)||"null");if(typeof saved?.id==="string"&&typeof saved.fingerprint==="string")request.current=saved; } catch { /* Ignore unrelated incomplete browser data. */ }
    void loadHistory().catch(e=>{if(alive.current)setError(message(e));});
    return()=>{alive.current=false;};
  },[projectId]);
  useEffect(()=>{
    if(!active(run))return;
    let disposed=false,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{
        const next=await api<Run>(`/api/canvas-runs/${run!.id}`);
        if(disposed)return;
        setRun(next);
        const signature=JSON.stringify(next.nodes.map(node=>[node.node_id,node.output_version_id]));
        if(!seen.current.has(signature)){seen.current.add(signature);if(next.nodes.some(n=>n.output_version_id))changed.current();}
        if(!active(next))void loadHistory();
      }catch(e){if(!disposed)setError(`进度暂时无法读取，后台运行仍保留：${message(e)}`);}
      if(!disposed)timer=setTimeout(()=>void poll(),1200);
    };
    timer=setTimeout(()=>void poll(),300);
    return()=>{disposed=true;clearTimeout(timer);};
  },[run?.id,run?.status]);
  function invalidate(){setPlan(undefined);setError("");}
  async function preview(){
    setBusy("plan");setError("");
    try{setPlan(await api<Plan>(base+"/plan",{method:"POST",body:JSON.stringify({scope,node_ids:scope==="downstream"?selectedNodeIds:undefined,force})}));}
    catch(e){setError(message(e));}finally{setBusy("");}
  }
  async function start(){
    if(!plan?.valid)return;
    setBusy("start");setError("");
    const payload={scope,node_ids:scope==="downstream"?selectedNodeIds:undefined,force,revision:plan.revision},fingerprint=JSON.stringify(payload);
    if(request.current?.fingerprint!==fingerprint)request.current={fingerprint,id:crypto.randomUUID()};
    try{localStorage.setItem(key,JSON.stringify(request.current));}catch{/* Idempotent retry remains in memory. */}
    try{
      const next=await api<Run>(base,{method:"POST",body:JSON.stringify({...payload,request_id:request.current.id})});
      setRun(next);setPlan(undefined);request.current=undefined;localStorage.removeItem(key);await loadHistory();
    }catch(e){setError(message(e));}finally{setBusy("");}
  }
  async function action(kind:"retry"|"cancel"){
    if(!run)return;setBusy(kind);setError("");
    try{setRun(await api<Run>(`/api/canvas-runs/${run.id}/${kind}`,{method:"POST",body:"{}"}));}
    catch(e){setError(message(e));}finally{setBusy("");}
  }
  const steps=plan?.nodes||run?.nodes||[];
  return createPortal(<div className="canvas-run-shade" role="presentation"><section ref={dialog} tabIndex={-1} className="canvas-run-panel" role="dialog" aria-modal="true" aria-labelledby="canvas-run-title">
    <header><div><h2 id="canvas-run-title">画布自动编排</h2><p>参考连线和卡片引用决定依赖；上游完成后，下游使用实际输出的固定版本。</p></div><button onClick={onClose} aria-label="关闭自动编排">×</button></header>
    <div className="canvas-run-body">
      <fieldset disabled={!!busy||active(run)} className="canvas-run-options"><label>执行范围<select value={scope} onChange={e=>{setScope(e.target.value as "all"|"downstream");invalidate();}}><option value="all">整张画布</option><option value="downstream" disabled={!selectedNodeIds.length}>选中节点及下游（{selectedNodeIds.length} 个起点）</option></select></label><label className="canvas-run-check"><input type="checkbox" checked={force} onChange={e=>{setForce(e.target.checked);invalidate();}}/>强制重做全部执行节点</label><button onClick={()=>void preview()}>{busy==="plan"?"检查中…":"检查依赖与执行计划"}</button></fieldset>
      <p className="canvas-run-help">默认复用以前运行中输入和配置均未改变的结果；选中下游时会包含必需的上游。故事关系线不触发生成。运行采用启动时的快照，失败重试也使用原快照。</p>
      {error&&<div role="alert" className="canvas-run-error">{error}</div>}
      {plan&&<div className="canvas-run-summary"><strong>{plan.valid?`预检通过 · ${plan.nodes.length} 个节点`:`预检未通过 · ${plan.errors.length} 个问题`}</strong><span>{plan.nodes.filter(n=>n.action==="generate").length} 个生成 · {plan.nodes.filter(n=>n.action==="reuse").length} 个复用</span>{plan.errors.map((issue,i)=><p role="alert" key={i}>{issue.node_id?`${issue.node_id}：`:""}{issue.message}</p>)}<button disabled={!plan.valid||!!busy||active(run)} onClick={()=>void start()}>{busy==="start"?"正在提交…":"按此计划开始执行"}</button></div>}
      {run&&!plan&&<div className="canvas-run-summary"><strong>{labels[run.status]||run.status} · {Math.round(run.progress*100)}%</strong><progress max={1} value={run.progress}/>{active(run)?<button disabled={!!busy||run.status==="cancelling"} onClick={()=>void action("cancel")}>停止后续执行</button>:["failed","cancelled"].includes(run.status)?<button disabled={!!busy} onClick={()=>void action("retry")}>按原快照重试未完成节点</button>:null}<small>已提交且无法撤回的任务会继续收集结果，后续节点不再提交。</small></div>}
      <ol className="canvas-run-steps">{steps.map((step,index)=><li key={step.node_id} data-state={step.status||step.action}><div className="canvas-run-index">{index+1}</div><div className="canvas-run-step-content"><button className="canvas-run-locate" onClick={()=>onLocate(step.node_id)}>{step.title}</button><span>{step.label||({image:"图片",video:"视频",audio:"配音"}[step.kind]||step.kind)} · {labels[step.status||step.action||""]||step.reason}</span><small>{step.dependencies.length?`等待：${step.dependencies.map(id=>steps.find(n=>n.node_id===id)?.title||id).join("、")}`:"无生成依赖"}</small>{step.job_status==="unknown"&&<p role="status">上游提交状态待核对；不会重复提交或继续下游。</p>}{step.job_progress!=null&&step.status==="running"&&<progress max={1} value={step.job_progress}/>} {step.message&&<small>{step.message}</small>}{step.error&&<p role="alert">{step.error}</p>}{plan&&step.reason&&<small>{step.reason}</small>}{step.output_version_id&&<a href={mediaUrl(step.output_version_id,"original")} target="_blank" rel="noreferrer">查看本次固定结果</a>}</div></li>)}</ol>
      {!steps.length&&<p className="canvas-run-empty">先检查计划，确认需要生成和复用的节点。关闭面板不会停止已提交的运行。</p>}
      {!!history.length&&<label className="canvas-run-history">历史运行<select value={run?.id||""} onChange={e=>{setPlan(undefined);setRun(history.find(item=>item.id===e.target.value));}}>{history.map(item=><option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()} · {labels[item.status]||item.status} · {item.nodes.length} 节点</option>)}</select></label>}
    </div>
    <footer><span>生成素材进入项目资产库；已有选用版本保留，新结果可在节点历史中审核采用。</span><button onClick={onClose}>关闭</button></footer>
  </section></div>, document.body);
}
