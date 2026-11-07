import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ArrowUp,AtSign,Headphones,LoaderCircle,Music2,Plus,Settings2,Square,Upload,X} from 'lucide-react';
import {api,ApiError,mediaUrl,uploadAsset} from './api';
import {Modal} from './ui';
import StudioSelect from './StudioSelect';
import type {AssetPage} from './types';
import type {GenerationDraft,GenerationJob,ImageReference,SpeechOptions} from './generationTypes';
import {activeGenerationStates} from './generationTypes';
import {GenerationProgress,useGenerationJob} from './GenerationProgress';
import {ReferenceTile,useReferencePreview} from './ReferenceMedia';
import PromptEditor from './PromptEditor';
import {promptParts,referenceId,referencesAfterPromptEdit} from './referenceModel';
import AudioWorkflow,{speechDefaults,SpeechControls} from './AudioWorkflow';
import type {AudioProfile,EmotionMode} from './AudioWorkflow';
import './video.css';
import './speech.css';

export const defaultSpeechDraft=(profile?:AudioProfile):GenerationDraft=>({kind:'audio',mode:'text_to_image',workflow_id:'builtin-indextts25-local',prompt:'',references:[],parameters:{seed:-1},speech_options:{...speechDefaults,...profile?.defaults}});
type Props={projectId:string;nodeId:string;draft?:GenerationDraft;locked?:boolean;canvasReferences:ImageReference[];onChange:(draft:GenerationDraft)=>void;onBeginEdit:()=>void;onBeforeSubmit:()=>Promise<void>;onRemoveConnections:(ids:string[])=>void;onAssetsChange:()=>void};
type VoiceRole='voice'|'emotion';
const roleOf=(reference:ImageReference,index:number):VoiceRole=>reference.role==='voice'||reference.role==='emotion'?reference.role:index===0?'voice':'emotion';
const ordered=(refs:ImageReference[])=>refs.map((r,index)=>({...r,role:roleOf(r,index)})).sort((a,b)=>a.role==='voice'&&b.role!=='voice'?-1:a.role!=='voice'&&b.role==='voice'?1:0);
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);

function CompareAudio({version}:{version:string}){
  const [variant,setVariant]=useState('original'),[failed,setFailed]=useState(false);
  return failed?<a href={mediaUrl(version,'original',true)} download>播放失败，下载原件试听</a>:<audio aria-label="对比试听音频" src={mediaUrl(version,variant)} controls preload="metadata" onPlay={event=>{const current=event.currentTarget;current.closest('.speech-compare-list')?.querySelectorAll('audio').forEach(element=>{if(element!==current)element.pause();});}} onError={()=>{if(variant==='original')setVariant('preview');else setFailed(true);}}/>;
}
function AudioComparison({references,jobs,onClose}:{references:ImageReference[];jobs:GenerationJob[];onClose:()=>void}){
  const outputs=jobs.flatMap(job=>job.outputs.map(output=>({...output,job}))).filter((output,index,all)=>all.findIndex(item=>item.version_id===output.version_id)===index).slice(0,6);
  return createPortal(<Modal title="配音对比试听" onClose={onClose} className="speech-compare-modal"><div className="speech-compare-list"><p>播放一项时会暂停其它音频。先比较角色音色与情绪，再决定采用哪个生成候选。</p>{ordered(references).map((ref,index)=><article key={referenceId(ref)}><div><strong>{roleOf(ref,index)==='voice'?'角色音色原件':'情绪参考原件'}</strong><small>{ref.title}</small><a href={mediaUrl(ref.version_id,'original',true)} download>下载原件</a></div><CompareAudio version={ref.version_id}/></article>)}{outputs.map((output,index)=><article key={output.version_id}><div><strong>生成候选 {index+1}</strong><small>{new Date(output.job.created_at).toLocaleString('zh-CN')}</small><a href={mediaUrl(output.version_id,'original',true)} download>下载候选</a></div><CompareAudio version={output.version_id}/></article>)}{!outputs.length&&<p>此配音卡尚无生成候选；生成完成后可在这里对比。</p>}</div></Modal>,document.body);
}

export default function AudioComposer(props:Props){
  const draft={...defaultSpeechDraft(),...props.draft};const latest=useRef(draft);latest.current=draft;
  const [profile,setProfile]=useState<AudioProfile>(),[busy,setBusy]=useState(false),[error,setError]=useState(''),[picker,setPicker]=useState(false),[managing,setManaging]=useState(false),[advanced,setAdvanced]=useState(false);
  const [pickerRole,setPickerRole]=useState<VoiceRole>('voice'),[mode,setMode]=useState<EmotionMode>(draft.speech_options?.use_emo_text?'text':draft.references.some((r,index)=>roleOf(r,index)==='emotion')?'audio':'preset');
  const [compare,setCompare]=useState(false),[candidates,setCandidates]=useState<GenerationJob[]>([]);
  const [tab,setTab]=useState<'canvas'|'library'>('canvas'),[library,setLibrary]=useState<ImageReference[]>([]),[search,setSearch]=useState(''),[page,setPage]=useState(0),[total,setTotal]=useState(0);
  const file=useRef<HTMLInputElement>(null),composing=useRef(false),caret=useRef(0);
  const job=useGenerationJob(draft.last_job_id),active=!!job&&activeGenerationStates.has(job.status),blocked=!!props.locked||busy||!!draft.pending_submission||active;
  const {hoverReference,openReference,renderReferencePreview}=useReferencePreview();
  const refs=ordered(draft.references),voice=refs.find(r=>r.role==='voice'),emotion=refs.find(r=>r.role==='emotion'),options={...speechDefaults,...draft.speech_options};
  function change(patch:Partial<GenerationDraft>){latest.current={...latest.current,...patch};props.onChange(latest.current);}
  useEffect(()=>{if(options.use_emo_text)setMode('text');else if(emotion)setMode('audio');},[options.use_emo_text,emotion?.version_id]);
  useEffect(()=>{let alive=true;api<AudioProfile>('/api/audio/settings').then(value=>{if(alive)setProfile(value);}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[]);
  useEffect(()=>{if(!picker||tab!=='library')return;let alive=true;api<AssetPage>(`/api/assets?type=audio&search=${encodeURIComponent(search)}&limit=30&offset=${page*30}`).then(p=>{if(alive){setTotal(p.total);setLibrary(p.items.map(a=>({id:a.current_version_id,version_id:a.current_version_id,title:a.name,source:'mention',media_type:'audio'})));}}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[picker,tab,search,page]);
  useEffect(()=>{if(!compare)return;let alive=true;api<{items:GenerationJob[]}>(`/api/generations?project_id=${encodeURIComponent(props.projectId)}&limit=500`).then(value=>{if(alive)setCandidates(value.items.filter(item=>item.source_node_id===props.nodeId&&item.status==='succeeded'));}).catch(e=>{if(alive)setError(errorText(e));});return()=>{alive=false;};},[compare,props.projectId,props.nodeId,job?.status]);
  function withoutMentions(prompt:string,current:ImageReference[],removed:ImageReference[]){const ids=new Set(removed.map(referenceId));return promptParts(prompt,current).map(part=>part.type==='text'?part.text:ids.has(part.reference_id)?'':'@'+(current.find(r=>referenceId(r)===part.reference_id)?.title||'')).join('');}
  function remove(ref:ImageReference){if(blocked)return;props.onBeginEdit();const current=latest.current,next=ordered(current.references).filter(r=>referenceId(r)!==referenceId(ref));change({references:next,prompt:withoutMentions(current.prompt,current.references,[ref]),subject_node_id:next.find(r=>r.role==='voice')?.node_id});if(ref.edge_id)props.onRemoveConnections([ref.edge_id]);}
  function selectMode(next:EmotionMode){
    if(blocked)return;props.onBeginEdit();setMode(next);const current=latest.current,normalized=ordered(current.references),removed=next==='audio'?[]:normalized.filter(ref=>ref.role==='emotion');
    change({speech_options:{...speechDefaults,...current.speech_options,use_emo_text:next==='text'},references:normalized.filter(ref=>!removed.includes(ref)),prompt:withoutMentions(current.prompt,current.references,removed)});
    if(removed.length)props.onRemoveConnections(removed.flatMap(ref=>ref.edge_id?[ref.edge_id]:[]));
    if(next==='audio'&&!normalized.some(ref=>ref.role==='emotion')){setPickerRole('emotion');setPicker(true);setTab('canvas');}
    if(next==='text')setAdvanced(true);
  }
  function applyReference(input:ImageReference,role:VoiceRole){
    const current=latest.current,normalized=ordered(current.references),replaced=normalized.filter(ref=>ref.role===role),remaining=normalized.filter(ref=>ref.role!==role);
    let title=input.title,suffix=2;while(remaining.some(ref=>ref.title===title))title=`${input.title} · ${suffix++}`;
    const target:ImageReference={...input,id:crypto.randomUUID(),title,role,media_type:'audio',source:'mention',edge_id:undefined};
    const at=Math.min(caret.current,current.prompt.length),before=current.prompt.slice(0,at),typingMention=role==='voice'&&/@[^\s@]*$/u.test(before);
    const prompt=typingMention?withoutMentions(before.replace(/@[^\s@]*$/u,''),current.references,replaced)+'@'+title+' '+withoutMentions(current.prompt.slice(at),current.references,replaced):withoutMentions(current.prompt,current.references,replaced);
    const references=ordered([...remaining,target]);
    props.onBeginEdit();change({references,prompt,subject_node_id:references.find(ref=>ref.role==='voice')?.node_id,...(role==='emotion'?{speech_options:{...speechDefaults,...current.speech_options,use_emo_text:false}}:{})});
    if(role==='emotion')setMode('audio');props.onRemoveConnections(replaced.flatMap(ref=>ref.edge_id?[ref.edge_id]:[]));setPicker(false);setError('');
  }
  function choose(ref:ImageReference){if(!blocked)applyReference(ref,pickerRole);}
  async function upload(files:FileList|null){if(!files?.length)return;const role=pickerRole;setBusy(true);try{const asset=await uploadAsset(files[0],{projectId:props.projectId});if(asset.type!=='audio')throw new Error('请选择音频文件。');if(!asset.version.duration||asset.version.duration<2||asset.version.duration>30)throw new Error('参考音频应为 2–30 秒，请裁剪后重新选择。文件已保留在资产库。');applyReference({version_id:asset.imported_version_id||asset.current_version_id,title:asset.name,source:'mention',media_type:'audio'},role);props.onAssetsChange();}catch(e){setError(errorText(e));}finally{setBusy(false);if(file.current)file.current.value='';}}
  const referencesValid=refs.filter(ref=>ref.role==='voice').length===1&&refs.filter(ref=>ref.role==='emotion').length<=1&&refs.length<=2;
  const modeValid=mode==='audio'?!!emotion&&profile?.capabilities?.emotion_reference!==false:mode==='text'?options.use_emo_text&&!!options.emo_text?.trim()&&!emotion&&profile?.capabilities?.emotion_text!==false:!emotion&&!options.use_emo_text;
  const nodeNeedsUpdate=profile?.capabilities?.studio_quality===false;
  const valid=!nodeNeedsUpdate&&referencesValid&&modeValid&&promptParts(draft.prompt,refs).some(part=>part.type==='text'&&part.text.trim());
  async function submit(){if(props.locked||busy||active||(!latest.current.pending_submission&&!valid))return;setBusy(true);setError('');try{let request=latest.current.pending_submission;if(!request){const d=latest.current,references=ordered(d.references);request={kind:'audio',project_id:props.projectId,source_node_id:props.nodeId,subject_node_id:d.subject_node_id||references.find(r=>r.role==='voice')?.node_id,workflow_id:'builtin-indextts25-local',prompt:d.prompt,prompt_parts:promptParts(d.prompt,references),references:references.map(r=>({...r,id:referenceId(r)})),speech_options:{...speechDefaults,...d.speech_options},parameters:d.parameters,result_policy:'review',placement:{x:0,y:0},request_id:crypto.randomUUID()};change({pending_submission:request,pending_request_id:request.request_id});}await props.onBeforeSubmit();const result=await api<GenerationJob>('/api/generations',{method:'POST',body:JSON.stringify(request)});change({last_job_id:result.id,pending_submission:undefined,pending_request_id:undefined});await props.onBeforeSubmit();}catch(e){setError(errorText(e));if(e instanceof ApiError)change({pending_submission:undefined,pending_request_id:undefined});}finally{setBusy(false);}}
  async function cancel(interrupt=false){if(!job)return;setBusy(true);try{await api(`/api/generations/${job.id}/cancel`,{method:'POST',body:JSON.stringify({interrupt_running:interrupt})});}catch(e){if(e instanceof ApiError&&(e.detail as {code?:string})?.code==='generation_interrupt_confirmation'&&window.confirm(job.status==='unknown'?'原配音可能仍在生成。结束本地跟踪不会撤回原任务；核对后结束跟踪？':'确认中断当前配音任务？'))await cancel(true);else setError(errorText(e));}finally{setBusy(false);}}
  function openPicker(role:VoiceRole){setPickerRole(role);setPicker(true);setSearch('');setPage(0);}
  const choices=(tab==='canvas'?props.canvasReferences:library).filter(r=>r.media_type==='audio'&&r.title.toLowerCase().includes(search.toLowerCase()));
  return <section className="video-composer nodrag nopan nowheel" aria-label="人物配音" onPointerDown={e=>e.stopPropagation()} onWheel={e=>e.stopPropagation()}>
    <header className="video-composer-tools"><span className="video-composer-label">人物配音 · {options.quality==='studio'?'录音室':'标准'}</span><div><button title="配音参数" aria-expanded={advanced} onClick={()=>setAdvanced(!advanced)}><Settings2 size={16}/></button></div></header>
    <div className="video-reference-strip speech-reference-strip">{refs.map((ref,index)=><div key={referenceId(ref)}><ReferenceTile reference={ref} index={index} badge={ref.role==='voice'?'角色音色':'情绪参考'} disabled={blocked} onHover={hoverReference} onOpen={openReference} onRemove={()=>remove(ref)}/><small className="speech-reference-label">{ref.title}</small></div>)}<button className="video-add-reference" disabled={blocked} title="选择人物音色" onClick={()=>openPicker('voice')}><Plus/><small>{voice?'更换角色音色':'角色音色'}</small></button>{mode==='audio'&&<button className="video-add-reference" disabled={blocked} title="选择情绪参考" onClick={()=>openPicker('emotion')}><Plus/><small>{emotion?'更换情绪参考':'情绪参考'}</small></button>}</div>
    <div className="speech-quick-mode"><span>演绎</span><StudioSelect aria-label="配音快速演绎方式" disabled={blocked} value={mode} onChange={e=>selectMode(e.target.value as EmotionMode)}><option value="preset">情绪预设</option><option value="text" disabled={profile?.capabilities?.emotion_text===false}>文字指导情绪{profile?.capabilities?.emotion_text===false?'（需情绪模型）':''}</option><option value="audio" disabled={profile?.capabilities?.emotion_reference===false}>参考情绪音频</option></StudioSelect><button title="对比试听" disabled={!refs.length&&!job?.outputs?.length} onClick={()=>setCompare(true)}><Headphones size={16}/></button></div>
    {picker&&<div className="video-picker"><header><div><button onClick={()=>setTab('canvas')} className={tab==='canvas'?'active':''}>从画布选择</button><button onClick={()=>setTab('library')} className={tab==='library'?'active':''}>资产库音频</button><button disabled={blocked} onClick={()=>file.current?.click()}><Upload size={14}/>本地添加</button></div><button title="关闭参考选择" onClick={()=>setPicker(false)}><X size={16}/></button></header><p className="speech-mode-summary">选择{pickerRole==='voice'?'角色音色：固定说话人声音':'情绪参考：提供表演情绪，保留角色音色'} · 2–30 秒单人语音</p><input aria-label="搜索音色" placeholder="搜索人物或音频" value={search} onChange={e=>{setSearch(e.target.value);setPage(0);}}/><div className="video-picker-grid">{choices.map(ref=><button key={referenceId(ref)} disabled={blocked} onClick={()=>choose(ref)}><Music2/><span>{ref.title}</span></button>)}{!choices.length&&<p>在人物主体绑定音色，或导入 2–30 秒参考音频。</p>}</div>{tab==='library'&&total>30&&<footer><button disabled={!page} onClick={()=>setPage(page-1)}>上一页</button><span>{page+1}</span><button disabled={(page+1)*30>=total} onClick={()=>setPage(page+1)}>下一页</button></footer>}</div>}
    <input type="file" accept="audio/*" hidden ref={file} onChange={e=>void upload(e.target.files)}/>
    <PromptEditor value={draft.prompt} references={refs} disabled={blocked} placeholder="输入要说的台词，@ 可选择角色音色。演绎指导和发音修正请填在配音参数中。" onReferenceHover={hoverReference} onFocus={props.onBeginEdit} onChange={(value,position)=>{caret.current=position;const references=referencesAfterPromptEdit(latest.current.prompt,value,latest.current.references);change({prompt:value,references,subject_node_id:ordered(references).find(ref=>ref.role==='voice')?.node_id});if(!composing.current&&value.slice(0,position).endsWith('@')){openPicker('voice');setTab('canvas');}}} onCompositionStart={()=>{composing.current=true;}} onCompositionEnd={()=>{composing.current=false;}} onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!composing.current&&valid&&profile?.ready){e.preventDefault();void submit();}}}/>
    <footer className="video-controls"><button className="video-control" onClick={()=>setManaging(true)}>IndexTTS 2.5 <span className="video-local-mark">本地</span></button><span className="video-output-count">1 段 · {options.speed} ×</span><button className="video-control" title="引用人物音色" disabled={blocked} onClick={()=>{openPicker('voice');setTab('canvas');}}><AtSign size={17}/></button><span className="video-control-spacer"/>{active&&job?.can_cancel?<button className="video-control" title={job.status==='unknown'?'结束配音任务跟踪':'取消配音任务'} disabled={busy} onClick={()=>void cancel()}><Square size={17}/></button>:<button className="video-submit" aria-label={draft.pending_submission?'重新确认配音提交':'生成配音'} disabled={!!props.locked||busy||active||(!draft.pending_submission&&(!valid||!profile?.ready))} onClick={()=>void submit()}>{busy?<LoaderCircle className="spin" size={18}/>:<ArrowUp size={20}/>}</button>}</footer>
    <GenerationProgress job={job} pending={!!draft.pending_submission} compact/>
    <div className="video-status"><span>{voice?`音色：${voice.title} · ${mode==='audio'?'音频情绪':mode==='text'?'文字情绪':'预设情绪'}`:'请选择角色音色'}</span><span>{nodeNeedsUpdate?'节点需更新':profile?.ready?'本地就绪':'本地未就绪'}</span></div>
    {job&&!active&&<p className="video-job-status">{job.message}{job.error&&<span className="error">{typeof job.error==='string'?job.error:job.error.message}</span>}</p>}
    {(error||profile?.errors.length||!referencesValid&&refs.length>0)&&<p className="video-notice" role="alert">{error||(!referencesValid&&refs.length>0?'保留一份角色音色和最多一份情绪参考，请移除重复引用。':profile?.errors.join('；'))}</p>}
    {nodeNeedsUpdate&&<p className="video-notice" role="alert">当前本地配音节点尚未支持新版参数，请更新节点后生成；已保留你的音色、台词和演绎设置。</p>}
    {profile?.capabilities?.emotion_text===false&&mode!=='text'&&<p className="speech-mode-summary">文字情绪模型尚未就绪，预设和音频参考可按本机能力使用。</p>}
    {advanced&&<div className="video-advanced"><SpeechControls value={options} disabled={blocked} mode={mode} onModeChange={selectMode} capabilities={profile?.capabilities} onChange={(speech_options:SpeechOptions)=>{props.onBeginEdit();change({speech_options});}}/><label>随机种子<input type="number" aria-label="配音种子" min={-1} disabled={blocked} value={draft.parameters.seed??-1} onFocus={props.onBeginEdit} onChange={e=>change({parameters:{seed:Number(e.target.value)}})}/></label><p>参考音频需为 2–30 秒清晰单人语音。语速与停顿不能保证精确时长；生成后请先对比试听，再到多轨剪辑对齐画面。</p></div>}
    {managing&&<AudioWorkflow onClose={()=>setManaging(false)} onSaved={setProfile}/>}{compare&&<AudioComparison references={refs} jobs={job?.status==='succeeded'?[job,...candidates.filter(item=>item.id!==job.id)]:candidates} onClose={()=>setCompare(false)}/>} {renderReferencePreview(refs)}
  </section>;
}
