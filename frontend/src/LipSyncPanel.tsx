import {useEffect,useRef,useState} from 'react';
import {api,ApiError,mediaUrl} from './api';
import {Modal} from './ui';
import {GenerationProgress} from './GenerationProgress';
import {activeGenerationStates,type GenerationJob} from './generationTypes';
import type {Asset,AssetPage,AssetVersion,CanvasData} from './types';
import './lipsync.css';

type Props={projectId:string;onClose:()=>void;onChanged:()=>void;initialVideoNodeId?:string};
type Profile={ready:boolean;errors:string[];name:string};
type LipRequest={kind:'video';mode:string;workflow_id:string;prompt:string;project_id:string;source_node_id:string;request_id:string;result_policy:'review';references:{id:string;role:string;media_type:string;version_id:string;node_id?:string;title?:string;source:string}[];parameters:{steps:number;cfg:number;seed:number};lip_sync_options:{audio_offset:number;video_start:number;duration:number|null;face_mode:string;face_box:number[]|null}};
type Submission={request:LipRequest;created_at:number;job_id?:string};
type TrackedJob=GenerationJob&{request_id?:string};
const prefix=(projectId:string)=>`manju:lipsync-submission:${projectId}:`;
const submissionKey=(value:Submission)=>prefix(value.request.project_id)+value.request.request_id;
function validRequest(value:unknown,projectId:string):value is LipRequest {
  const r=value as Partial<LipRequest>|null;
  return !!r&&r.project_id===projectId&&r.workflow_id==='builtin-latentsync15-local'&&typeof r.request_id==='string'&&!!r.request_id&&typeof r.source_node_id==='string'&&Array.isArray(r.references)&&r.references.length===2&&r.references.every(ref=>typeof ref.version_id==='string'&&['video','audio'].includes(ref.role))&&!!r.parameters&&!!r.lip_sync_options;
}
function savedSubmissions(projectId:string,document:CanvasData):Submission[]{
  const records=new Map<string,Submission>();
  try{for(let i=0;i<localStorage.length;i++){const key=localStorage.key(i);if(!key?.startsWith(prefix(projectId)))continue;try{const value=JSON.parse(localStorage.getItem(key)||'null') as Submission;if(validRequest(value?.request,projectId))records.set(value.request.request_id,value);}catch{/* Ignore incomplete browser data. */}}}catch{/* Server canvas is also a durable recovery source. */}
  for(const node of document.nodes){const value=(node.data.generation as {pending_submission?:unknown}|undefined)?.pending_submission;if(validRequest(value,projectId)&&!records.has(value.request_id))records.set(value.request_id,{request:value,created_at:0});}
  return [...records.values()].sort((a,b)=>Number(!!a.job_id)-Number(!!b.job_id)||b.created_at-a.created_at);
}
export default function LipSyncPanel({projectId,onClose,onChanged,initialVideoNodeId}:Props){
  const [assets,setAssets]=useState<Asset[]>([]),[profile,setProfile]=useState<Profile>();
  const [videoId,setVideoId]=useState(''),[audioId,setAudioId]=useState(''),[offset,setOffset]=useState(0),[start,setStart]=useState(0),[duration,setDuration]=useState(5);
  const [manual,setManual]=useState(false),[box,setBox]=useState([0,0,160,200]),[steps,setSteps]=useState(20),[guidance,setGuidance]=useState(1.5);
  const [seed,setSeed]=useState(-1),[autoDuration,setAutoDuration]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[job,setJob]=useState<GenerationJob>();
  const [draftId,setDraftId]=useState(''),[pending,setPending]=useState<Submission>(),[loading,setLoading]=useState(true);
  const video=assets.find(a=>a.current_version_id===videoId),audio=assets.find(a=>a.current_version_id===audioId);
  const picture=useRef<HTMLDivElement>(null),preview=useRef<HTMLVideoElement>(null),drag=useRef<{x:number;y:number}|null>(null);
  const changed=useRef(onChanged);changed.current=onChanged;
  const alive=useRef(true),submitting=useRef(false),initialNode=useRef(initialVideoNodeId);
  const draftPrompt=useRef('按人物配音同步口型');
  function remember(value:Submission){try{localStorage.setItem(submissionKey(value),JSON.stringify(value));}catch{setNotice('浏览器记录未写入；已保存的画布节点仍保留完整提交参数。');}}
  function restoreForm(request:LipRequest){
    setVideoId(request.references.find(ref=>ref.role==='video')?.version_id||'');setAudioId(request.references.find(ref=>ref.role==='audio')?.version_id||'');
    const options=request.lip_sync_options;setOffset(options.audio_offset);setStart(options.video_start);setAutoDuration(options.duration==null);setDuration(options.duration??5);setManual(options.face_mode==='manual');setBox(options.face_box||[0,0,160,200]);setSteps(request.parameters.steps);setGuidance(request.parameters.cfg);setSeed(request.parameters.seed);draftPrompt.current=request.prompt||'按人物配音同步口型';setDraftId(request.source_node_id);
  }
  async function settleCanvas(value:Submission,jobId?:string){
    for(let attempt=0;attempt<2;attempt++){
      const doc=await api<CanvasData>(`/api/projects/${projectId}/canvas`),node=doc.nodes.find(n=>n.id===value.request.source_node_id);
      const generation=node?.data.generation as Record<string,unknown>|undefined;
      if(!node||!generation||!validRequest(generation.pending_submission,projectId)||generation.pending_submission.request_id!==value.request.request_id)return;
      const next={...generation};delete next.pending_submission;delete next.pending_request_id;if(jobId)next.last_job_id=jobId;
      node.data={...node.data,generation:next};
      try{await api(`/api/projects/${projectId}/canvas`,{method:'PUT',body:JSON.stringify({...doc,request_id:crypto.randomUUID()})});return;}
      catch(e){if(!(e instanceof ApiError&&e.status===409&&attempt===0))throw e;}
    }
  }
  async function accepted(value:Submission,result:GenerationJob){
    remember({...value,job_id:result.id});if(alive.current){setJob(result);setPending(undefined);setError('');setNotice('已确认同一口型任务，可关闭此窗口继续编辑。');}
    try{await settleCanvas(value,result.id);changed.current();}catch{if(alive.current)setNotice('任务已确认；画布提交标记暂未清理，下次打开会继续核对。');}
  }
  useEffect(()=>{alive.current=true;let disposed=false;void Promise.all([api<AssetPage>(`/api/assets?project_id=${projectId}&limit=500`),api<CanvasData>(`/api/projects/${projectId}/canvas`),api<Profile>('/api/lipsync/settings')]).then(async([page,document,engine])=>{
    const items=[...page.items];for(let n=500;n<page.total;n+=500)items.push(...(await api<AssetPage>(`/api/assets?project_id=${projectId}&limit=500&offset=${n}`)).items);
    if(disposed)return;setAssets(items);setProfile(engine);
    const selected=document.nodes.find(n=>n.id===initialNode.current)?.data as {asset_version_id?:string;generation_id?:string;generation?:Partial<LipRequest>&{last_job_id?:string}}|undefined;
    const v=items.find(a=>a.type==='video'&&a.current_version_id===selected?.asset_version_id)||items.find(a=>a.type==='video');
    if(v){setVideoId(v.current_version_id);setDuration(Math.min(5,v.version.duration||5));}
    setAudioId(items.find(a=>a.type==='audio')?.current_version_id||'');
    const selectedDraft=selected?.generation?.workflow_id==='builtin-latentsync15-local'?selected.generation:undefined;
    if(selectedDraft){
      const references=[...(selectedDraft.references||[])],missingRole=()=>['video','audio'].some(role=>!references.some(ref=>ref.role===role&&ref.version_id));
      const priorJobId=selectedDraft.last_job_id||selected?.generation_id;
      // A DAG can store dependencies as edges only. Once executed, its request
      // snapshot is the fixed source of truth even if upstream cards changed.
      if(missingRole()&&priorJobId){
        try{
          const prior=await api<GenerationJob>(`/api/generations/${priorJobId}`);
          const snapshot=prior.request as Partial<LipRequest>|undefined;
          if(prior.source_node_id===initialNode.current&&snapshot?.workflow_id==='builtin-latentsync15-local'){
            for(const ref of snapshot.references||[])if(['video','audio'].includes(ref.role||'')&&!references.some(item=>item.role===ref.role&&item.version_id))references.push({...ref,source:ref.source||'edge'});
            if(!disposed)setJob(prior);
          }
        }catch{if(!disposed)setNotice('暂时无法读取上次口型任务的固定输入，请稍后重开；不会自动改用上游的新版本。');}
      }else if(missingRole()){
        for(const edge of document.edges.filter(edge=>edge.target===initialNode.current&&edge.data?.role==='reference')){
          const source=document.nodes.find(node=>node.id===edge.source),role=source?.data.kind;
          if(source&&typeof source.data.asset_version_id==='string'&&(role==='video'||role==='audio')&&!references.some(ref=>ref.role===role&&ref.version_id))references.push({id:edge.id,source:'edge',role,media_type:role,version_id:source.data.asset_version_id,node_id:source.id,title:typeof source.data.title==='string'?source.data.title:undefined});
        }
      }
      if(disposed)return;
      restoreForm({...selectedDraft,project_id:projectId,source_node_id:initialNode.current!,references,parameters:{steps:20,cfg:1.5,seed:-1,...selectedDraft.parameters},lip_sync_options:{audio_offset:0,video_start:0,duration:Math.min(5,v?.version.duration||5),face_mode:'auto',face_box:null,...selectedDraft.lip_sync_options}} as LipRequest);
      for(const ref of references)if(!items.some(a=>a.current_version_id===ref.version_id)){
        try{const found=await api<{asset:Asset;version:AssetVersion}>(`/api/versions/${ref.version_id}`);items.push({...found.asset,id:found.asset.id+':'+ref.version_id,name:found.asset.name+' · 固定版本',current_version_id:ref.version_id,version:found.version});}catch{/* Keep original fixed input IDs for repair. */}
      }
      if(disposed)return;setAssets([...items]);
    }
    const records=savedSubmissions(projectId,document),record=records.find(value=>value.request.source_node_id===initialNode.current)||(selectedDraft?undefined:records[0]);
    if(record){
      setPending(record);if(!selectedDraft||!record.job_id)restoreForm(record.request);setNotice('发现尚待核对的口型提交，参数已冻结。可重试同一请求，避免重复生成。');
      for(const ref of record.request.references)if(!items.some(a=>a.current_version_id===ref.version_id)){
        try{const found=await api<{asset:Asset;version:AssetVersion}>(`/api/versions/${ref.version_id}`);items.push({...found.asset,id:found.asset.id+':'+ref.version_id,name:found.asset.name+' · 固定版本',current_version_id:ref.version_id,version:found.version});}catch{/* The frozen request remains available if an input needs repair. */}
      }
      if(disposed)return;setAssets([...items]);
      try{
        const found=record.job_id?await api<TrackedJob>(`/api/generations/${record.job_id}`):(await api<{items:TrackedJob[]}>(`/api/generations?project_id=${projectId}&limit=500`)).items.find(item=>item.request_id===record.request.request_id);
        if(found&&!disposed){if(activeGenerationStates.has(found.status))restoreForm(record.request);await accepted(record,found);}
      }catch{if(!disposed)setNotice('暂时无法核对原任务；已保留原请求，重试不会创建新的请求编号。');}
    }else if(selectedDraft?.last_job_id){
      try{const found=await api<GenerationJob>(`/api/generations/${selectedDraft.last_job_id}`);if(!disposed)setJob(found);}catch{/* An archived node can retain editable parameters without a live task. */}
    }
  }).catch(e=>{if(!disposed)setError(String(e));}).finally(()=>{if(!disposed)setLoading(false);});return()=>{disposed=true;alive.current=false;};},[projectId]);
  useEffect(()=>{if(!job||!activeGenerationStates.has(job.status))return;let alive=true;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{const value=await api<GenerationJob>(`/api/generations/${job.id}`);if(!alive)return;setJob(value);if(value.status==='succeeded'){setNotice('同步视频已进入项目资产库，原视频与配音保留。');changed.current();}}catch(e){if(alive)setError(String(e));}if(alive)timer=setTimeout(()=>void poll(),2000);};timer=setTimeout(()=>void poll(),700);return()=>{alive=false;clearTimeout(timer);};},[job?.id,job?.status]);
  const active=!!job&&activeGenerationStates.has(job.status),blocked=busy||active||!!pending||loading,width=video?.version.width||1,height=video?.version.height||1;
  const effectiveDuration=autoDuration?Math.max(0,(video?.version.duration||0)-start):duration;
  const overflow=!!audio?.version.duration&&audio.version.duration+offset>effectiveDuration+.05;
  function coordinate(e:React.PointerEvent){const rect=picture.current!.getBoundingClientRect();return{x:Math.max(0,Math.min(width,(e.clientX-rect.left)/rect.width*width)),y:Math.max(0,Math.min(height,(e.clientY-rect.top)/rect.height*height))};}
  async function replay(value:Submission){
    try{const result=await api<GenerationJob>('/api/generations',{method:'POST',body:JSON.stringify(value.request)});await accepted(value,result);}
    catch(e){
      const code=e instanceof ApiError?(e.detail as {code?:string})?.code:undefined;
      // Only an explicit validation rejection releases editing. Network/5xx and
      // idempotency conflicts retain the exact request for reconciliation.
      if(e instanceof ApiError&&[400,404,422].includes(e.status)||e instanceof ApiError&&e.status===409&&['generation_source_busy','asset_trashed'].includes(code||'')){
        try{await settleCanvas(value);localStorage.removeItem(submissionKey(value));if(alive.current){setPending(undefined);setNotice('服务明确拒绝了这次提交，可修改参数后重新生成。');}changed.current();}catch{/* Keep the durable request if cleanup could not be confirmed. */}
      }
      throw e;
    }
  }
  async function submit(generate:boolean){if(submitting.current||active||loading||pending&&!generate)return;submitting.current=true;setBusy(true);setError('');try{
    if(pending){await replay(pending);return;}
    const doc=await api<CanvasData>(`/api/projects/${projectId}/canvas`);
    const prior=doc.nodes.find(n=>n.id===draftId)?.data.generation as Partial<LipRequest>|undefined;
    function sourceFor(role:string,versionId:string){const previous=prior?.references?.find(ref=>ref.role===role&&ref.version_id===versionId);return doc.nodes.find(n=>n.id!==draftId&&n.id===previous?.node_id)||doc.nodes.find(n=>n.id!==draftId&&n.type==='media'&&(n.data as {asset_version_id?:string}).asset_version_id===versionId);}
    const sourceVideo=sourceFor('video',videoId),sourceAudio=sourceFor('audio',audioId);
    const nodeId=draftId||'lip-sync-'+crypto.randomUUID(),key=crypto.randomUUID();setDraftId(nodeId);
    function reference(role:string,versionId:string,sourceId:string|undefined,title:string|undefined){const previous=prior?.references?.find(ref=>ref.role===role&&ref.version_id===versionId);return {id:role,source:'mention',...previous,role,media_type:role,version_id:versionId,node_id:sourceId,title:previous?.title||title};}
    const references=[reference('video',videoId,sourceVideo?.id,video?.name),reference('audio',audioId,sourceAudio?.id,audio?.name)];
    const generation={kind:'video',mode:'text_to_image',workflow_id:'builtin-latentsync15-local',prompt:draftPrompt.current,references,parameters:{steps,cfg:guidance,seed},lip_sync_options:{audio_offset:offset,video_start:start,duration:autoDuration?null:duration,face_mode:manual?'manual':'auto',face_box:manual?box:null}};
    const request={...generation,project_id:projectId,source_node_id:nodeId,result_policy:'review',request_id:key} as LipRequest;
    const durableGeneration=generate?{...generation,pending_request_id:key,pending_submission:request}:generation;
    const old=doc.nodes.find(n=>n.id===nodeId);
    if(old?.data.locked||old&&(old.type!=='media'||old.data.kind!=='video'))throw new Error('原节点已锁定或类型已改变，请重新选择口型节点。');
    const otherPending=(old?.data.generation as {pending_submission?:unknown}|undefined)?.pending_submission;
    if(validRequest(otherPending,projectId)){
      const value={request:otherPending,created_at:Date.now()};remember(value);setPending(value);restoreForm(otherPending);
      throw new Error('此节点已有待核对的提交，已恢复原请求。请先核对，避免覆盖其他窗口的任务。');
    }
    if(old)old.data={...old.data,generation:durableGeneration};else doc.nodes.push({id:nodeId,type:'media',position:{x:(sourceVideo?.position.x||0)+390,y:sourceVideo?.position.y||0},style:{width:360,height:240},data:{kind:'video',title:`口型 · ${video?.name||'视频'}`,generation:durableGeneration}});
    const sources=new Set([sourceVideo?.id,sourceAudio?.id].filter(Boolean));
    doc.edges=doc.edges.filter(edge=>edge.target!==nodeId||edge.data?.role!=='reference'||sources.has(edge.source));
    for(const source of [sourceVideo,sourceAudio])if(source&&!doc.edges.some(e=>e.source===source.id&&e.target===nodeId&&e.data?.role==='reference'))doc.edges.push({id:crypto.randomUUID(),source:source.id,target:nodeId,data:{role:'reference'}});
    await api(`/api/projects/${projectId}/canvas`,{method:'PUT',body:JSON.stringify({...doc,request_id:crypto.randomUUID()})});changed.current();
    if(generate){const value={request:JSON.parse(JSON.stringify(request)) as LipRequest,created_at:Date.now()};remember(value);setPending(value);await replay(value);}
    else setNotice('已创建口型节点，可连接上游并使用画布自动编排。');
  }catch(e){if(alive.current)setError(String(e));}finally{submitting.current=false;if(alive.current)setBusy(false);}}
  const output=job?.outputs?.[0]?.version_id;
  return <Modal title="精确口型同步" onClose={onClose} wide className="lipsync-modal"><div className="lipsync-content">
    <p>将已有视频中的口型与独立配音对齐。原始视频与配音保留，同步结果作为新视频进入资产库。</p>
    <p role="status">{profile?.ready?'LatentSync 1.5 · 本机就绪':profile?.errors.join('；')||'正在检查模型…'}</p>
    <fieldset className="lipsync-fields" disabled={blocked}><div className="lipsync-columns"><div>
      <label>人物视频<select aria-label="口型视频素材" value={videoId} disabled={blocked} onChange={e=>{setVideoId(e.target.value);setAutoDuration(false);const item=assets.find(a=>a.current_version_id===e.target.value);setStart(0);setDuration(Math.min(5,item?.version.duration||5));}}><option value="">选择视频</option>{assets.filter(a=>a.type==='video').map(a=><option key={a.id} value={a.current_version_id}>{a.name}</option>)}</select></label>
      {video&&<><div className="lipsync-picture" ref={picture} style={{aspectRatio:`${width}/${height}`}} onPointerDown={e=>{if(!manual||blocked)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);drag.current=coordinate(e);}} onPointerMove={e=>{if(!drag.current||blocked)return;const p=coordinate(e),a=drag.current;setBox([Math.round(Math.min(a.x,p.x)),Math.round(Math.min(a.y,p.y)),Math.round(Math.abs(p.x-a.x)),Math.round(Math.abs(p.y-a.y))]);}} onPointerUp={()=>{drag.current=null;}}>
        <video ref={preview} src={mediaUrl(videoId,'original')} controls={!manual} preload="metadata"/>
        {manual&&<div className="lipsync-face-box" style={{left:box[0]/width*100+'%',top:box[1]/height*100+'%',width:box[2]/width*100+'%',height:box[3]/height*100+'%'}}/>}
      </div><label>定位参考帧<input aria-label="口型参考帧" type="range" min={0} max={video.version.duration||5} step={.04} defaultValue={0} onChange={e=>{if(preview.current){preview.current.pause();preview.current.currentTime=Number(e.target.value);}}}/></label></>}
    </div><div>
      <label>人物配音<select aria-label="口型配音素材" value={audioId} disabled={blocked} onChange={e=>{setAudioId(e.target.value);}}><option value="">选择配音</option>{assets.filter(a=>a.type==='audio').map(a=><option key={a.id} value={a.current_version_id}>{a.name}</option>)}</select></label>
      {audioId&&<audio controls src={mediaUrl(audioId,'original')}/>}
      <div className="lipsync-grid"><label>视频入点（秒）<input aria-label="口型视频入点" type="number" min={0} step={.04} value={start} onChange={e=>setStart(Number(e.target.value))}/></label><label>片段时长（秒）<input aria-label="口型片段时长" type="number" min={.2} max={120} step={.04} value={effectiveDuration} onChange={e=>{setAutoDuration(false);setDuration(Number(e.target.value));}}/></label><label>配音起点（秒）<input aria-label="口型配音起点" type="number" min={0} step={.04} value={offset} onChange={e=>setOffset(Number(e.target.value))}/></label><label>采样步数<input aria-label="口型采样步数" type="number" min={10} max={50} value={steps} onChange={e=>setSteps(Number(e.target.value))}/></label><label>同步强度<input aria-label="口型同步强度" type="number" min={1} max={3} step={.1} value={guidance} onChange={e=>setGuidance(Number(e.target.value))}/></label></div>
      <label className="lipsync-check"><input type="checkbox" checked={manual} onChange={e=>setManual(e.target.checked)}/>手工框选人脸并跟踪</label>
      {manual?<><p>在画面上拖出人脸框，包含额头到下巴。适用于动画人物或自动检测失败的镜头。</p><div className="lipsync-grid">{['左','上','宽','高'].map((name,i)=><label key={name}>{name}<input aria-label={`人脸框${name}`} type="number" value={box[i]} min={0} onChange={e=>setBox(box.map((v,n)=>n===i?Number(e.target.value):v))}/></label>)}</div></>:<p>自动定位可见人脸。背影、严重遮挡或多人镜头请先裁剪到明确的说话人物。</p>}
      {overflow&&<p role="alert" className="error">配音超过片段长度，请调整起点或时长。</p>}
    </div></div></fieldset>
    {pending&&<p className="lipsync-pending" role="status">提交结果尚待核对，完整参数与输入版本已保留。请使用“核对并重试原提交”；刷新或关闭后也可恢复。</p>}
    {job&&<div className="lipsync-job"><GenerationProgress job={job}/><p>{job.message}</p>{job.error&&<p className="error">{typeof job.error==='string'?job.error:job.error.message}</p>}</div>}
    {output&&<div className="lipsync-output"><video src={mediaUrl(output,'original')} controls/><a className="button secondary" href={mediaUrl(output,'original')+'&download=true'} download>下载同步视频</a></div>}
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <footer className="workflow-editor-footer"><button className="button secondary" disabled={blocked||!videoId||!audioId||overflow} onClick={()=>void submit(false)}>保存为流程节点</button><button className="button primary" disabled={busy||active||loading||(!pending&&(!profile?.ready||!videoId||!audioId||overflow))} onClick={()=>void submit(true)}>{busy?'正在核对提交…':active?'口型同步进行中':pending?'核对并重试原提交':'生成同步视频'}</button></footer>
  </div></Modal>;
}
