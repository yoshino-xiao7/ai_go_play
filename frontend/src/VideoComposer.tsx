import {ReferenceTile,useReferencePreview} from "./ReferenceMedia";
import StudioSelect from "./StudioSelect";
import VideoWorkflow from "./VideoWorkflow";
import VideoReferenceEditor from "./VideoReferenceEditor";
import {videoEngines} from "./videoProfile";
import type {VideoDefaults,VideoProfile as Profile} from "./videoProfile";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, AtSign, Check, ChevronDown, Clock3, Crosshair, Film, LoaderCircle, Music2, Plus, RefreshCw, Settings2, Square, Upload, X } from "lucide-react";
import { api, ApiError, mediaUrl, uploadAsset } from "./api";
import type { AssetPage } from "./types";
import type { GenerationDraft, GenerationJob, H3Guide, ImageReference, VideoEngine } from "./generationTypes";
import { activeGenerationStates, generationStateLabels } from "./generationTypes";
import PromptEditor from "./PromptEditor";
import type { PromptEditorHandle } from "./PromptEditor";
import { normalizeVideoReferences, promptParts, referenceId, referencesAfterPromptEdit } from "./referenceModel";
import VideoParameterPopover, { VideoDuration } from "./VideoParameterPopover";
import {GenerationProgress, useGenerationJob} from "./GenerationProgress";

export const defaultVideoDraft=(defaults?:VideoDefaults):GenerationDraft=>({kind:"video",mode:"text_to_image",video_mode:"text",workflow_id:"builtin-h3-local",video_options:{engine:"native",sampler:"res_multistep",scheduler:"simple",ref_image_size:"1024"},prompt:"",references:[],parameters:{width:defaults?.width??864,height:defaults?.height??480,steps:defaults?.steps??20,cfg:defaults?.cfg??1,seed:defaults?.seed??-1},duration:defaults?.duration??4,audio:defaults?.audio??true});

type Props={projectId:string;nodeId:string;draft?:GenerationDraft;locked?:boolean;cameraMotionLabel?:string;canvasReferences:ImageReference[];onChange:(draft:GenerationDraft)=>void;onBeginEdit:()=>void;onBeforeSubmit:()=>Promise<void>;onRemoveConnections:(ids:string[])=>void;onAssetsChange:()=>void};
type H3Profile = Profile & {
  h3_guides_ready?: boolean;
  limits?: {guides?: number; frame_count_min?: number; frame_count_max?: number; frame_count_step?: number};
};

const modeNames={text:"文生视频",frames:"首尾帧",reference:"全参考"};
const message=(error:unknown)=>error instanceof Error?error.message:String(error);
const guideKind = {image:"图片",video:"视频",audio:"音频"};
const h3Fps = 24;
const durationFrames = (duration: number) => Math.ceil((duration * h3Fps - 5) / 17) * 17 + 5;

export default function VideoComposer(props:Props){
  const {hoverReference,openReference,renderReferencePreview}=useReferencePreview();
  const draft={...defaultVideoDraft(),...props.draft,parameters:{...defaultVideoDraft().parameters,...props.draft?.parameters}};
  const latest=useRef(draft);latest.current=draft;
  const knownReferences=useRef(new Map<string,ImageReference>());
  draft.references.forEach(ref=>knownReferences.current.set(referenceId(ref),ref));
  const editor=useRef<PromptEditorHandle>(null),fileInput=useRef<HTMLInputElement>(null),caret=useRef(draft.prompt.length),composing=useRef(false);
  const [profile,setProfile]=useState<H3Profile>(),[managing,setManaging]=useState(false),[advanced,setAdvanced]=useState(false);
  const [editingReference,setEditingReference]=useState<ImageReference>();
  const [picker,setPicker]=useState<"reference"|"guide"|null>(null),[tab,setTab]=useState<"canvas"|"library">("canvas"),[search,setSearch]=useState(""),[library,setLibrary]=useState<ImageReference[]>([]),[page,setPage]=useState(0),[total,setTotal]=useState(0);
  const [guidesOpen, setGuidesOpen] = useState(!!props.draft?.h3_guides?.length);
  const [error,setError]=useState(""),[busy,setBusy]=useState(false),[job,setJob]=useState<GenerationJob>(),[uploading,setUploading]=useState(false);
  const [menu,setMenu]=useState<"model"|"size"|"mode"|"duration"|null>(null);
  const modelButton=useRef<HTMLButtonElement>(null),sizeButton=useRef<HTMLButtonElement>(null),modeButton=useRef<HTMLButtonElement>(null),durationButton=useRef<HTMLButtonElement>(null);
  const menuAnchors={model:modelButton,size:sizeButton,mode:modeButton,duration:durationButton};
  const blocked=!!props.locked||busy||!!draft.pending_submission;
  const mode=draft.video_mode||"text",refs=draft.references;
  const engine=draft.video_options?.engine||"native",turbo=engine==="turbo";
  const guides = draft.h3_guides ?? [];
  const {guides: guideLimit = 12, frame_count_min: minFrames = 5, frame_count_max: maxFrames = 362, frame_count_step: frameStep = 17} = profile?.limits ?? {};
  const exactFrames = draft.frame_count;
  const frameCount = exactFrames ?? durationFrames(draft.duration ?? 4);
  const invalidFrameCount = exactFrames !== undefined && (!Number.isInteger(exactFrames) || exactFrames < minFrames || exactFrames > maxFrames || (exactFrames - minFrames) % frameStep !== 0);
  const canAddGuide = engine !== "director" && profile?.h3_guides_ready !== false && guides.length < guideLimit;
  const environment=profile?.engines?.[engine]??profile,ready=environment?.ready;
  const active=!!job&&(activeGenerationStates.has(job.status)||job.status==="unknown");
  const liveJob=useGenerationJob(draft.last_job_id);
  useEffect(()=>{if(liveJob)setJob(liveJob);else if(!draft.last_job_id)setJob(undefined);},[liveJob,draft.last_job_id]);
  useEffect(()=>{if(blocked)setMenu(null);},[blocked]);
  function toggleMenu(value:NonNullable<typeof menu>){setPicker(null);setMenu(menu===value?null:value);}
  function togglePicker(kind: "reference" | "guide") {
    setMenu(null);
    setPicker(current => current === kind ? null : kind);
    setTab("canvas");
  }
  function change(patch:Partial<GenerationDraft>){if(props.draft?.workflow_id==='builtin-latentsync15-local')return;const next={...latest.current,...patch};latest.current=next;props.onChange(next);}
  useEffect(()=>{
    if(blocked)return;
    const current=latest.current, normalized=normalizeVideoReferences(current.prompt,current.references);
    if(normalized.references!==current.references)change(normalized);
  },[draft.references,blocked]);
  async function refresh(){try{const result=await api<H3Profile>("/api/video/settings");setProfile(result);}catch(e){setError(message(e));}}
  useEffect(()=>{void refresh();},[]);
  useEffect(()=>{
    if(!picker||tab!=="library")return;
    let alive=true;
    api<AssetPage>(`/api/assets?search=${encodeURIComponent(search)}&limit=30&offset=${page*30}`).then(result=>{if(alive){setTotal(result.total);setLibrary(result.items.map(asset=>({id:asset.current_version_id,version_id:asset.current_version_id,title:asset.name,source:"mention",media_type:asset.type})));}}).catch(e=>{if(alive)setError(message(e));});
    return()=>{alive=false;};
  },[picker,tab,search,page]);
  function setMode(value:typeof mode){
    props.onBeginEdit();
    change({video_mode:value,references:refs.map((ref,index)=>({...ref,role:value==="frames"?(index===0?"first_frame":"last_frame"):"reference"}))});
  }
  function selectEngine(value:VideoEngine){
    props.onBeginEdit();
    const reference=value==="turbo";
    change({video_options:{...draft.video_options,engine:value},...(reference?{
      video_mode:"reference",
      references:refs.map(ref=>({...ref,role:"reference"})),
    }:{})});
    setMenu(null);
  }
  function addReference(input:ImageReference){
    if(blocked)return;
    const current=latest.current;
    const existing=current.references.find(ref=>ref.version_id===input.version_id);
    if(!existing&&current.references.length>=12){setError("最多引用 12 个素材。");return;}
    if(!existing&&current.video_mode==="frames"&&((input.media_type||"image")!=="image"||current.references.length>=2)){setError("首尾帧分别最多一张图片，其他素材请使用全参考模式。");return;}
    const base=input.title.replace(/@/g,"")||"参考素材";let title=base,index=2;
    while(current.references.some(ref=>ref.title===title))title=base+" · "+index++;
    const ref:ImageReference=existing||{...input,id:crypto.randomUUID(),title,source:"mention",edge_id:undefined,role:current.video_mode==="frames"?(current.references.some(r=>r.role==="first_frame")?"last_frame":"first_frame"):"reference",use_description:true};
    title=ref.title;
    const at=Math.min(caret.current,current.prompt.length),before=current.prompt.slice(0,at).replace(/@[^\s@]*$/u,"");
    const prompt=before+"@"+title+" "+current.prompt.slice(at);
    props.onBeginEdit();change({references:existing?current.references:[...current.references,ref],video_mode:current.video_mode==="text"?"reference":current.video_mode,prompt});
    caret.current=before.length+title.length+2;setPicker(null);setError("");requestAnimationFrame(()=>{editor.current?.focus();editor.current?.setSelection(caret.current);});
  }
  function addGuide(input: ImageReference) {
    if (blocked || !canAddGuide) return;
    const current = latest.current.h3_guides ?? [];
    if (current.length >= guideLimit) return;
    props.onBeginEdit();
    change({h3_guides:[...current, {
      id:crypto.randomUUID(), version_id:input.version_id, media_type:input.media_type ?? "image", frame_idx:0, title:input.title,
    }]});
    setGuidesOpen(true);
    setPicker(null);
    setError("");
  }
  function updateGuide(index: number, patch?: Partial<H3Guide>) {
    if (blocked) return;
    props.onBeginEdit();
    const current = latest.current.h3_guides ?? [];
    change({h3_guides:patch ? current.map((guide,i)=>i===index?{...guide,...patch}:guide) : current.filter((_,i)=>i!==index)});
  }
  function remove(ref:ImageReference){
    props.onBeginEdit();
    const next=latest.current.references.filter(item=>referenceId(item)!==referenceId(ref));
    change({references:next,prompt:promptParts(latest.current.prompt,latest.current.references).map(part=>part.type==="text"?part.text:part.reference_id===referenceId(ref)?"":"@"+latest.current.references.find(item=>referenceId(item)===part.reference_id)!.title).join("")});
    if(ref.edge_id)props.onRemoveConnections([ref.edge_id]);
  }
  function changePrompt(value:string,position:number){
    if(blocked)return;
    caret.current=position;
    const current=latest.current;
    const references=referencesAfterPromptEdit(current.prompt,value,current.references);
    // PromptEditor's undo restores text; restore its frozen material binding too.
    const known=[...knownReferences.current.values()];
    for(const part of promptParts(value,known)){
      if(part.type!=="reference")continue;
      const ref=knownReferences.current.get(part.reference_id);
      if(ref&&!references.some(item=>item.version_id===ref.version_id&&(item.role||"reference")===(ref.role||"reference")))references.push({...ref,source:"mention",edge_id:undefined});
    }
    change({prompt:value,references});
    if(!composing.current&&value.slice(0,position).endsWith("@")){setPicker("reference");setTab("canvas");}
  }
  async function upload(files:FileList|null){
    if(!files?.length)return;setUploading(true);setError("");
    const add = picker === "guide" ? addGuide : addReference;
    try{for(const file of Array.from(files)){const asset=await uploadAsset(file,{projectId:props.projectId});add({version_id:asset.imported_version_id||asset.current_version_id,title:asset.name,source:"mention",media_type:asset.type});}props.onAssetsChange();}catch(e){setError(message(e));}finally{setUploading(false);if(fileInput.current)fileInput.current.value="";}
  }
  const invalidReference=turbo&&mode!=="reference"?"Turbo 8 步使用全参考模式。":mode==="text"&&refs.length?"文生视频不使用参考素材，请移除素材或切换模式。":mode==="frames"&&(!refs.length||refs.length>2||refs.some(ref=>(ref.media_type||"image")!=="image")||new Set(refs.map(ref=>ref.role)).size!==refs.length)?"请选择一张首帧，或分别绑定首帧和尾帧。":mode==="reference"&&!refs.length?"添加图片、视频或音频作为参考。":"";
  const invalid = engine === "director" && (guides.length || exactFrames !== undefined)
    ? "定帧引导与精确采样帧数可用于原生和 Turbo 流程。"
    : invalidFrameCount ? `采样帧数须在 ${minFrames}–${maxFrames} 之间，以 ${minFrames} 为起点、步长为 ${frameStep}。`
    : guides.length > guideLimit ? `最多添加 ${guideLimit} 个定帧引导。`
    : guides.length && profile?.h3_guides_ready === false ? "ComfyUI 当前缺少 MiniMaxH3AddGuide 节点。"
    : guides.some(guide => !Number.isInteger(guide.frame_idx) || guide.frame_idx < 0 || guide.frame_idx >= frameCount)
    ? `定帧引导须使用 0–${frameCount-1} 的整数帧索引。`
    : guides.some(guide => guide.media_type !== "image" && ((guide.clip_start ?? 0)<0 || (guide.clip_end != null && guide.clip_end <= (guide.clip_start ?? 0))))
    ? "引导片段的开始时间须为非负，结束时间须晚于开始。"
    : invalidReference;
  async function cancel(interrupt=false){
    if(!job)return;setBusy(true);setError("");
    try{setJob(await api<GenerationJob>(`/api/generations/${job.id}/cancel`,{method:"POST",body:JSON.stringify({interrupt_running:interrupt})}));}
    catch(e){if(e instanceof ApiError&&(e.detail as {code?:string})?.code==="generation_interrupt_confirmation"&&window.confirm(job.status==="unknown"?"原视频可能仍在生成。结束跟踪不会撤回原任务；核对后结束本地跟踪？":"视频正在生成，确认中断当前这个任务？"))await cancel(true);else setError(message(e));}
    finally{setBusy(false);}
  }
  async function submit(){
    if(props.draft?.workflow_id==='builtin-latentsync15-local'){setError('请使用口型节点的专用编辑面板。');return;}
    if(props.locked||busy||active||uploading||(!latest.current.pending_submission&&(invalid||!ready||!latest.current.prompt.trim())))return;setBusy(true);setError("");
    try{
      let request=latest.current.pending_submission;
      if(!request){
        const value=latest.current;
        request={kind:"video",video_options:value.video_options,video_mode:value.video_mode,duration:value.duration,frame_count:value.frame_count,h3_guides:value.h3_guides?.length?value.h3_guides.map(({title: _title,...guide})=>guide):undefined,audio:value.audio,project_id:props.projectId,source_node_id:props.nodeId,workflow_id:"builtin-h3-local",prompt:value.prompt,prompt_parts:promptParts(value.prompt,value.references),references:value.references.map(ref=>({...ref,id:referenceId(ref)})),parameters:value.parameters,result_policy:"review",placement:{x:0,y:0},request_id:crypto.randomUUID()};
        change({pending_request_id:request.request_id,pending_submission:request});
      }
      await props.onBeforeSubmit();
      const result=await api<GenerationJob>("/api/generations",{method:"POST",body:JSON.stringify(request)});
      // A refilled draft became a new round: keep the lineage locally, clear the refill marker.
      const refilled=latest.current.refill_of;
      change({last_job_id:result.id,pending_request_id:undefined,pending_submission:undefined,refill_of:undefined,...(refilled?{round_links:{...(latest.current.round_links||{}),[result.id]:refilled.job_id}}:{})});setJob(result);await props.onBeforeSubmit();
    }catch(e){setError(message(e));if(e instanceof ApiError){change({pending_request_id:undefined,pending_submission:undefined});}}
    finally{setBusy(false);}
  }
  function dimensions(ratio:string,size:number){const [w,h]=ratio.split(":").map(Number),short=Math.min(w,h);change({parameters:{...latest.current.parameters,width:Math.min(1344,Math.round(size*w/short/32)*32),height:Math.min(1344,Math.round(size*h/short/32)*32)}});}
  const width=Number(draft.parameters.width||864),height=Number(draft.parameters.height||480),ratio=width===height?"1:1":width>height?"16:9":"9:16",size=Math.min(width,height);
  const choices=(tab==="canvas"?props.canvasReferences:library).filter(ref=>(tab!=="canvas"||ref.title.toLowerCase().includes(search.toLowerCase()))&&(picker==="guide"||mode!=="frames"||(ref.media_type||"image")==="image"));
  const guideRefs = guides.map((guide,index): ImageReference => ({
    ...guide, title:guide.title ?? `${guideKind[guide.media_type]}引导 ${index+1}`, source:"mention",
  }));
  return <section className="video-composer nodrag nopan nowheel" aria-label="视频创作" onPointerDown={e=>e.stopPropagation()} onWheel={e=>e.stopPropagation()}>
    <header className="video-composer-tools"><span className="video-composer-label">视频创作</span><div><button className="composer-rounds-link" title="查看这张卡片每一轮提交与结果" onClick={()=>window.dispatchEvent(new CustomEvent("manju:open-rounds",{detail:{nodeId:props.nodeId}}))}>结果轮次</button><button title="刷新本地模型状态" onClick={()=>void refresh()}><RefreshCw size={14}/></button><button title="视频工作流设置" aria-expanded={advanced} onClick={()=>{setMenu(null);setAdvanced(!advanced);}}><Settings2 size={16}/></button></div></header>
    {draft.refill_of && <div className="composer-refill" role="status"><span className="composer-refill-tag">回填</span><span>来自 {new Date(draft.refill_of.created_at).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"})} 的一轮：描述、参数和素材版本与当时一致。点生成会成为新的一轮，原记录不变。</span>{draft.refill_of.seed!==undefined&&(draft.parameters.seed===-1?<button disabled={blocked} onClick={()=>{props.onBeginEdit();change({parameters:{...latest.current.parameters,seed:draft.refill_of!.seed!}});}}>沿用原种子 {draft.refill_of.seed}</button>:<button disabled={blocked} onClick={()=>{props.onBeginEdit();change({parameters:{...latest.current.parameters,seed:-1}});}}>改用随机种子</button>)}<button aria-label="清除回填标记" disabled={blocked} onClick={()=>change({refill_of:undefined})}><X size={12}/></button></div>}
    {props.cameraMotionLabel && <div className="video-camera-motion" title="连接的运镜会在生成时加入 H3 的提示词"><Crosshair size={14} />运镜 · {props.cameraMotionLabel}</div>}
    <div className="video-reference-strip">
      {refs.map((ref,index)=><div className="video-reference-slot" key={referenceId(ref)}>
        <ReferenceTile reference={ref} index={index} disabled={blocked} onHover={hoverReference} onOpen={openReference} onRemove={()=>remove(ref)}
          onMove={direction=>{props.onBeginEdit();const next=[...latest.current.references];const target=index+direction;if(target<0||target>=next.length)return;[next[index],next[target]]=[next[target],next[index]];change({references:next});}} canMoveBack={index>0} canMoveForward={index<refs.length-1}/>
        {mode==="frames"&&<StudioSelect aria-label={`参考 ${index+1} 用途`} value={ref.role||"first_frame"} disabled={blocked} onChange={e=>{props.onBeginEdit();change({references:refs.map(item=>item===ref?{...item,role:e.target.value as ImageReference["role"]}:item)});}}><option value="first_frame">首帧</option><option value="last_frame">尾帧</option></StudioSelect>}
        <button className="video-reference-settings" aria-label={`设置参考 ${index+1}`} title="裁切、用途与片段" disabled={blocked} onClick={()=>setEditingReference(ref)}><Settings2 size={12}/>{ref.purpose==="identity"?"人物":ref.purpose==="voice"?"音色":ref.purpose==="camera"?"运镜":ref.crop&&ref.crop.width<1?"已裁切":"设置"}</button>
      </div>)}
      <button className="video-add-reference" title="添加参考素材" disabled={blocked||uploading} onClick={()=>togglePicker("reference")}>{uploading?<LoaderCircle className="spin"/>:<Plus/>}<small>参考素材</small></button>
    </div>
    {(engine!=="director"||guides.length>0)&&<section className="video-timed-guides" aria-label="H3 定帧引导">
      <div className="video-timed-guide-toolbar">
        <button type="button" className="video-timed-guide-toggle" aria-expanded={guidesOpen}
          onClick={()=>{if(guidesOpen&&picker==="guide")setPicker(null);setGuidesOpen(!guidesOpen);}}>
          <Clock3 size={14}/><span>定帧引导{guides.length>0&&` · ${guides.length}`}</span><ChevronDown size={12}/>
        </button>
        {guidesOpen&&<button type="button" className="video-timed-guide-add" disabled={blocked||uploading||!canAddGuide}
          aria-expanded={picker==="guide"} onClick={()=>togglePicker("guide")}><Plus size={14}/> 添加引导</button>}
      </div>
      {guidesOpen&&<>
        <p className="video-timed-guide-hint">从第 0 帧计数。图片固定在指定帧，视频与音频从指定帧起引导。</p>
        {guideRefs.map((ref,index)=>{
          const guide=guides[index],name=`引导 ${index+1}`;
          return <div className="video-timed-guide-row" key={guide.id ?? `${guide.version_id}-${index}`}>
            <div className="video-timed-guide-head">
              <button type="button" className="video-timed-guide-preview" title={`预览 ${ref.title}`} onClick={()=>openReference(ref)}>
                {guide.media_type==="audio"?<Music2 size={15}/>:<img src={mediaUrl(guide.version_id,"thumbnail")} alt=""/>}
                <span>{ref.title}</span><small>{guideKind[guide.media_type]}</small>
              </button>
              <label>帧<input type="number" min={0} max={frameCount-1} step={1} value={guide.frame_idx} disabled={blocked}
                aria-label={`${name}帧索引`} onChange={e=>updateGuide(index,{frame_idx:Number(e.target.value)})}/></label>
              <button type="button" title={`移除 ${name}`} aria-label={`移除 ${name}`} disabled={blocked} onClick={()=>updateGuide(index)}><X size={14}/></button>
            </div>
            {guide.media_type!=="image"&&<div className="video-timed-guide-clip">
              <label>开始秒<input type="number" min={0} step={0.01} value={guide.clip_start ?? ""} placeholder="0" disabled={blocked}
                aria-label={`${name}片段开始秒数`} onChange={e=>updateGuide(index,{clip_start:e.target.value===""?undefined:Number(e.target.value)})}/></label>
              <label>结束秒<input type="number" min={0} step={0.01} value={guide.clip_end ?? ""} placeholder="素材末尾" disabled={blocked}
                aria-label={`${name}片段结束秒数`} onChange={e=>updateGuide(index,{clip_end:e.target.value===""?undefined:Number(e.target.value)})}/></label>
              {guide.media_type==="video"&&<label className="video-timed-guide-audio"><input type="checkbox" checked={!!guide.use_audio}
                disabled={blocked} onChange={e=>updateGuide(index,{use_audio:e.target.checked})}/> 用原声引导</label>}
            </div>}
          </div>;
        })}
      </>}
    </section>}
    {picker&&<div className="video-picker" aria-label={picker==="guide"?"选择定帧引导素材":"选择参考素材"}><header><div><button className={tab==="canvas"?"active":""} onClick={()=>setTab("canvas")}>从画布选择</button><button className={tab==="library"?"active":""} onClick={()=>setTab("library")}>资产库</button><button disabled={blocked||uploading} onClick={()=>fileInput.current?.click()}><Upload size={14}/> 本地添加</button></div><button title="关闭素材选择" onClick={()=>setPicker(null)}><X size={16}/></button></header><input aria-label={picker==="guide"?"搜索定帧引导素材":"搜索参考素材"} placeholder="搜索图片、视频、音频或主体音色" value={search} onChange={e=>{setSearch(e.target.value);setPage(0);}}/><div className="video-picker-grid">{choices.map(ref=><button key={referenceId(ref)} disabled={blocked} title={ref.title} onClick={()=>picker==="guide"?addGuide(ref):addReference(ref)}>{ref.media_type==="audio"?<Music2 size={30}/>:<img src={mediaUrl(ref.version_id,"thumbnail")} alt=""/>}<span>{ref.title}</span><small>{guideKind[ref.media_type||"image"]}</small></button>)}{!choices.length&&<p>暂无可用素材，可从电脑添加。</p>}</div>{tab==="library"&&total>30&&<footer><button disabled={!page} onClick={()=>setPage(page-1)}>上一页</button><span>{page+1} / {Math.ceil(total/30)}</span><button disabled={(page+1)*30>=total} onClick={()=>setPage(page+1)}>下一页</button></footer>}</div>}
    <input ref={fileInput} type="file" hidden multiple accept="image/*,video/*,audio/*" onChange={e=>void upload(e.target.files)}/>
    <PromptEditor onReferenceHover={hoverReference} ref={editor} value={draft.prompt} references={refs} disabled={blocked} placeholder="描述镜头、人物动作与声音，输入 @ 引用素材。例：@角色 向镜头走来，风吹动衣摆，轻柔的脚步声。" onFocus={props.onBeginEdit} onChange={changePrompt} onKeyDown={e=>{if(e.key==="Enter"&&(e.ctrlKey||e.metaKey)&&!composing.current){e.preventDefault();if(!invalid&&ready&&draft.prompt.trim())void submit();}}} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}}/>
    <footer className="video-controls">
      <button ref={modelButton} className="video-control video-model-control" aria-label="视频模型" aria-haspopup="dialog" aria-expanded={menu==="model"} disabled={blocked} onClick={()=>toggleMenu("model")}>H3 {videoEngines[engine].short}<span className="video-local-mark">本地</span><ChevronDown size={12}/></button>
      <button ref={sizeButton} className="video-control" aria-label="视频画幅与清晰度" aria-haspopup="dialog" aria-expanded={menu==="size"} disabled={blocked} onClick={()=>toggleMenu("size")}>{ratio}<span className="video-control-dot">·</span>{size>=768?"768 原生":"480 试作"}<ChevronDown size={12}/></button>
      <span className="video-output-count" title="每次生成一个视频">1 个</span>
      <button ref={modeButton} className="video-control video-mode-control" aria-label="视频生成模式" aria-haspopup="dialog" aria-expanded={menu==="mode"} disabled={blocked||turbo} onClick={()=>toggleMenu("mode")}>{modeNames[mode]}<ChevronDown size={12}/></button>
      <button ref={durationButton} className="video-control" aria-label="视频时长" aria-haspopup="dialog" aria-expanded={menu==="duration"} disabled={blocked} onClick={()=>toggleMenu("duration")}>{exactFrames===undefined?`${draft.duration} s`:`${exactFrames} 帧`}<ChevronDown size={12}/></button>
      <button className="video-control video-icon-control" title="引用画布素材" disabled={blocked} onClick={()=>togglePicker("reference")}><AtSign size={17}/></button>
      <button className="video-control video-icon-control video-sound-control" aria-label="生成声音" aria-pressed={draft.audio!==false} title={draft.audio!==false?"生成声音已开启":"生成声音已关闭"} disabled={blocked} onClick={()=>{props.onBeginEdit();change({audio:draft.audio===false});}}><Music2 size={16}/>{draft.audio!==false&&<i/>}</button>
      <span className="video-control-spacer"/>
      {active&&job?.can_cancel?<button className="video-control video-cancel" title={job.status==="unknown"?"结束视频任务跟踪":"取消视频任务"} disabled={busy} onClick={()=>void cancel()}><Square size={17}/></button>:<button className="video-submit" aria-label={draft.pending_submission?"重新确认视频提交":"生成视频"} title={draft.pending_submission?"使用同一请求编号恢复，避免重复生成":"生成视频 · Ctrl+Enter"} disabled={props.locked||busy||uploading||active||(!draft.pending_submission&&(!ready||!!invalid||!draft.prompt.trim()))} onClick={()=>void submit()}>{busy||active?<LoaderCircle className="spin" size={18}/>:<ArrowUp size={20}/>}</button>}
    </footer>
    {menu&&!blocked&&<VideoParameterPopover key={menu} anchor={menuAnchors[menu]} label={{model:"选择视频模型",size:"选择画幅与清晰度",mode:"选择视频生成模式",duration:"选择视频生成时长"}[menu]} width={menu==="duration"?380:menu==="mode"?250:320} onClose={()=>setMenu(null)}>
      {menu==="duration"&&<>
        {exactFrames===undefined
          ? <VideoDuration value={draft.duration||4} onBegin={props.onBeginEdit} onChange={value=>change({duration:value})}/>
          : <button type="button" className="video-exact-frame-reset" onClick={()=>{props.onBeginEdit();change({frame_count:undefined});}}>恢复按秒设置</button>}
        {(engine!=="director"||exactFrames!==undefined)&&<label className="video-exact-frame-count">
          <span>精确采样帧数</span>
          <input aria-label="精确采样帧数" type="number" min={minFrames} max={maxFrames} step={frameStep}
            placeholder={String(durationFrames(draft.duration??4))} value={exactFrames ?? ""} onFocus={props.onBeginEdit}
            aria-invalid={invalidFrameCount} onChange={e=>change({frame_count:e.target.value===""?undefined:Number(e.target.value)})}/>
          <small>从 {minFrames} 到 {maxFrames} 帧，步长 {frameStep}。留空时按时长计算。</small>
        </label>}
      </>}
      {menu==="mode"&&<><div className="video-popover-caption">生成方式</div><div role="radiogroup" aria-label="视频生成模式">{Object.entries(modeNames).map(([key,value])=><button className="video-mode-option" role="radio" aria-checked={mode===key} key={key} onClick={()=>{setMode(key as typeof mode);setMenu(null);modeButton.current?.focus();}}><Film size={16}/><span><strong>{value}</strong><small>{{text:"用文字描述镜头和声音",frames:"用图片控制开场与结束画面",reference:"参考图片、视频和声音"}[key]}</small></span>{mode===key&&<Check size={17}/>}</button>)}</div></>}
      {menu==="size"&&<><div className="video-popover-caption">画面比例</div><div className="video-ratio-options" role="radiogroup" aria-label="视频画幅">{["16:9","9:16","1:1"].map(value=><button role="radio" aria-checked={ratio===value} key={value} onClick={()=>{props.onBeginEdit();dimensions(value,size);}}><i style={{width:value==="9:16"?14:24,height:value==="16:9"?14:24}}/><span>{value}</span></button>)}</div><div className="video-popover-caption">清晰度</div><div className="video-resolution-options" role="radiogroup" aria-label="视频分辨率">{[480,768].map(value=><button role="radio" aria-checked={(size>=768?768:480)===value} key={value} onClick={()=>{props.onBeginEdit();dimensions(ratio,value);}}><span>{value} <small>{value===480?"试作":"原生"}</small></span>{(size>=768?768:480)===value&&<Check size={15}/>}</button>)}</div><p className="video-popover-footnote">{width} × {height} 像素 · 尺寸按模型要求对齐</p></>}
      {menu==="model"&&<><div className="video-popover-caption">H3 执行流程</div>{(Object.keys(videoEngines) as VideoEngine[]).map(key=><button key={key} className="video-mode-option" role="radio" aria-checked={engine===key} disabled={key!=="native"&&!profile?.engines?.[key]?.ready||key==="director"&&(guides.length>0||exactFrames!==undefined)} onClick={()=>selectEngine(key)}><Film size={16}/><span><strong>{videoEngines[key].label}</strong><small>{key==="director"&&(guides.length>0||exactFrames!==undefined)?"切换前请移除定帧引导与精确采样帧数":videoEngines[key].description}</small></span>{engine===key&&<Check size={16}/>}</button>)}<p className="video-popover-footnote">{ready?"本地模型已就绪":"请先连接 ComfyUI 并检查模型"}</p><button className="video-manage-model" onClick={()=>{setMenu(null);setManaging(true);}}>管理工作流<Settings2 size={14}/></button></>}
    </VideoParameterPopover>}
    <div className="video-status"><span>{width} × {height} · {h3Fps} fps · {invalidFrameCount?"帧数待校正":`${frameCount} 帧 · ${(frameCount/h3Fps).toFixed(2)} 秒`}</span><span>{job?generationStateLabels[job.status]:ready?"本地就绪":"本地未就绪"}</span></div>
    <GenerationProgress job={job} pending={!!draft.pending_submission} compact/>
    {props.draft&&!props.draft.video_options&&Number(draft.parameters.cfg)===4&&<p className="video-notice">此卡片保留旧采样配置。<button disabled={blocked||active} onClick={()=>{props.onBeginEdit();change({parameters:{...draft.parameters,cfg:1,steps:20},video_options:{engine:'native',sampler:'res_multistep',scheduler:'simple',ref_image_size:'1024'}});}}>改用 H3 推荐配置</button></p>}
    {job&&!active&&<div className="video-job-status" role="status">{job.message}{job.error&&<span className="error">{typeof job.error==="string"?job.error:job.error.message}</span>}{job.status==="succeeded"&&<small>结果保留在当前卡片；再次生成会增加候选版本。</small>}</div>}
    {!!(error||invalid||environment?.errors.length)&&<p className="video-notice" role="alert">{error||invalid||environment?.errors.join("；")}</p>}
    {draft.pending_submission&&<p className="video-notice">提交记录已保留。可重新确认同一个任务；不要重复新建请求。</p>}
    {advanced&&<div className="video-advanced"><strong>本地 H3 工作流</strong><p>任务会保存模型、参数和参考素材版本。视频 / 音频每段 2–15 秒，各类合计不超过 15 秒；最多 9 张图片、3 段视频、3 段音频，总计 12 个。</p><div className="video-parameter-grid">{["steps","cfg","seed"].map(key=><label key={key}>{{steps:"采样步数",cfg:"CFG",seed:"种子（-1 随机）"}[key]}<input type="number" aria-label={key} value={turbo&&key!=="seed"?(key==="steps"?8:1):draft.parameters[key]??0} disabled={blocked||(turbo&&key!=="seed")} min={key==="steps"?1:key==="seed"?-1:0} max={key==="steps"?100:key==="cfg"?20:undefined} step={key==="cfg"?0.5:1} onFocus={props.onBeginEdit} onChange={e=>change({parameters:{...draft.parameters,[key]:Number(e.target.value)}})}/></label>)}</div><button disabled={blocked} onClick={()=>setManaging(true)}><Settings2 size={14}/>管理 H3 模型与默认参数</button><p>768 为本地生成档，不等同于云端 2K 增强。当前素材只发送至本机 ComfyUI，云端适配尚未实现。</p></div>}
    {advanced&&turbo&&<div className="video-advanced"><strong>Turbo 8 步全能参考</strong><p>固定使用 Euler / beta、CFG 1，参考图随输出尺寸处理。</p></div>}
    {advanced&&!turbo&&<div className="video-advanced video-quality-options"><label>参考图处理长边<StudioSelect aria-label="参考图处理长边" disabled={blocked} value={draft.video_options?.ref_image_size||"1024"} onChange={e=>change({video_options:{...draft.video_options,ref_image_size:e.target.value as NonNullable<GenerationDraft['video_options']>['ref_image_size']}})}>{['match','1024','1280','1536','max'].map(value=><option key={value} value={value}>{value==='match'?'跟随输出（节省显存）':value==='max'?'高保真（短边上限 2048）':value}</option>)}</StudioSelect></label><div className="video-parameter-grid"><label>采样器<StudioSelect aria-label="视频采样器" disabled={blocked} value={draft.video_options?.sampler||"res_multistep"} onChange={e=>change({video_options:{...draft.video_options,sampler:e.target.value as 'res_multistep'|'euler'}})}><option value="res_multistep">res_multistep</option><option value="euler">Euler</option></StudioSelect></label><label>调度器<StudioSelect aria-label="视频调度器" disabled={blocked} value={draft.video_options?.scheduler||"simple"} onChange={e=>change({video_options:{...draft.video_options,scheduler:e.target.value as 'simple'|'beta'|'normal'}})}>{['simple','beta','normal'].map(value=><option key={value}>{value}</option>)}</StudioSelect></label></div><button disabled={blocked} onClick={()=>{props.onBeginEdit();change({parameters:{...draft.parameters,cfg:1,steps:20},video_options:{...draft.video_options,sampler:'res_multistep',scheduler:'simple',ref_image_size:'1024'}});}}>恢复 H3 推荐采样：CFG 1 · 20 步</button><p>角色三视图先裁成单个视角，或先用图片创作生成镜头首帧，再使用首尾帧模式。Director 当前按单镜头运行，不会自动拆分长剧本。</p></div>}
    {editingReference&&<VideoReferenceEditor reference={editingReference} width={width} height={height} onClose={()=>setEditingReference(undefined)} onSave={ref=>{props.onBeginEdit();change({references:latest.current.references.map(item=>referenceId(item)===referenceId(ref)?ref:item)});}}/>}
    {renderReferencePreview([...refs,...guideRefs])}
    {managing&&<VideoWorkflow initialEngine={engine} onClose={()=>setManaging(false)} onSaved={setProfile}/>}
  </section>;
}
