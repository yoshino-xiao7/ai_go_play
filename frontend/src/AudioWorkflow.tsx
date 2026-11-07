import {useEffect,useState} from 'react';
import {api} from './api';
import {Modal} from './ui';
import StudioSelect from './StudioSelect';
import type {SpeechOptions} from './generationTypes';
import './speech.css';
export type SpeechCapabilities=Partial<Record<'emotion_text'|'emotion_reference'|'pronunciation'|'studio_quality'|'interval_silence'|'temperature',boolean>>;
export type AudioProfile={id:string;kind:'audio';name:string;ready:boolean;errors:string[];revision:number;defaults:SpeechOptions;capabilities?:SpeechCapabilities};
export type EmotionMode='preset'|'text'|'audio';
export const speechDefaults:SpeechOptions={language:'zh',speed:1,emotion:'reference',intensity:.5,use_emo_text:false,emo_text:'',pronunciation:'',interval_silence:200,quality:'studio',temperature:.8};
export const emotionNames:Record<string,string>={reference:'跟随音色',neutral:'自然',happy:'开心',angry:'生气',sad:'悲伤',afraid:'害怕',disgusted:'厌恶',melancholic:'低落',surprised:'惊讶',calm:'平静'};
export function SpeechControls({value,disabled,onChange,mode,onModeChange,capabilities}:{value:SpeechOptions;disabled?:boolean;onChange:(v:SpeechOptions)=>void;mode?:EmotionMode;onModeChange?:(mode:EmotionMode)=>void;capabilities?:SpeechCapabilities}){
  const options={...speechDefaults,...value},currentMode=mode||(options.use_emo_text?'text':'preset');
  const update=(patch:Partial<SpeechOptions>)=>onChange({...options,...patch});
  const setMode=(next:EmotionMode)=>{if(onModeChange)onModeChange(next);else update({use_emo_text:next==='text'});};
  return <div className="speech-controls"><div className="video-parameter-grid">
    <label>语言<StudioSelect aria-label="配音语言" disabled={disabled} value={options.language} onChange={e=>update({language:e.target.value})}>{Object.entries({zh:'中文',en:'英语',ja:'日语',es:'西班牙语',ar:'阿拉伯语'}).map(([id,name])=><option key={id} value={id}>{name}</option>)}</StudioSelect></label>
    <label>语速<StudioSelect aria-label="配音语速" disabled={disabled} value={options.speed} onChange={e=>update({speed:Number(e.target.value)})}>{[.5,.75,.85,.9,.95,1,1.05,1.1,1.15,1.25,1.5,2].map(v=><option key={v} value={v}>{v} ×</option>)}{![.5,.75,.85,.9,.95,1,1.05,1.1,1.15,1.25,1.5,2].includes(options.speed)&&<option value={options.speed}>{options.speed} ×</option>}</StudioSelect></label>
    <label>演绎方式<StudioSelect aria-label="配音演绎方式" disabled={disabled} value={currentMode} onChange={e=>setMode(e.target.value as EmotionMode)}><option value="preset">情绪预设</option><option value="text" disabled={capabilities?.emotion_text===false}>文字指导情绪{capabilities?.emotion_text===false?'（需安装情绪模型）':''}</option>{onModeChange&&<option value="audio" disabled={capabilities?.emotion_reference===false}>参考情绪音频{capabilities?.emotion_reference===false?'（需更新节点）':''}</option>}</StudioSelect></label>
    <label>合成质量<StudioSelect aria-label="配音合成质量" disabled={disabled||capabilities?.studio_quality===false} value={options.quality} onChange={e=>update({quality:e.target.value as SpeechOptions['quality']})}><option value="studio">录音室 · 40 步</option><option value="standard">标准 · 25 步</option></StudioSelect></label>
    {currentMode==='preset'&&<label>情绪<StudioSelect aria-label="配音情绪" disabled={disabled} value={options.emotion} onChange={e=>update({emotion:e.target.value})}>{Object.entries(emotionNames).map(([id,name])=><option key={id} value={id}>{name}</option>)}</StudioSelect></label>}<label>情绪强度 · {options.intensity.toFixed(2)}<input aria-label="配音情绪强度" disabled={disabled||currentMode==='preset'&&options.emotion==='reference'} type="range" min={0} max={.8} step={.05} value={options.intensity} onChange={e=>update({intensity:Number(e.target.value)})}/></label>
    <label>句间附加停顿（毫秒）<input aria-label="配音句间停顿" disabled={disabled||capabilities?.interval_silence===false} type="number" min={0} max={1500} step={50} value={options.interval_silence} onChange={e=>update({interval_silence:Math.max(0,Math.min(1500,Number(e.target.value)))})}/></label>
    <label>表达变化 · {options.temperature?.toFixed(2)}<input aria-label="配音表达变化" disabled={disabled||capabilities?.temperature===false} type="range" min={.5} max={1.2} step={.05} value={options.temperature} onChange={e=>update({temperature:Number(e.target.value)})}/></label>
    </div>
    {currentMode==='text'&&<label className="speech-wide-field">情绪文字指导<textarea aria-label="配音情绪文字" rows={2} maxLength={1000} disabled={disabled||capabilities?.emotion_text===false} placeholder="例如：先失落，接到母亲电话后放松，最后带着笑意。" value={options.emo_text} onChange={e=>update({emo_text:e.target.value})}/><small>模型将描述转换为情绪强度，建议强度不超过 0.6；请试听确认表演效果，指导文字不会作为台词朗读。</small></label>}
    {currentMode==='audio'&&<p className="speech-help">角色音色确定说话人，第二份音频提供情绪与表达参考；预设情绪和文字指导在此模式下停用。</p>}
    <label className="speech-wide-field">发音修正（每行一条）<textarea aria-label="配音发音修正" rows={2} maxLength={4000} disabled={disabled||capabilities?.pronunciation===false} placeholder={'末班车=MO4 BAN1 CHE1\n重庆=CHONG2 QING4'} value={options.pronunciation} onChange={e=>update({pronunciation:e.target.value})}/><small>中文拼音使用大写音节和声调数字；原始台词会完整保留。</small></label>
    {capabilities?.emotion_text===false&&<p className="speech-help">本机尚未启用文字情绪模型，可使用预设情绪或情绪参考音频。</p>}
    {capabilities&&['emotion_reference','pronunciation','studio_quality','interval_silence','temperature'].some(key=>capabilities[key as keyof SpeechCapabilities]===false)&&<p className="speech-help">部分参数需要更新本地 Manju IndexTTS 节点后启用。</p>}
  </div>;
}
export default function AudioWorkflow({onClose,onSaved}:{onClose:()=>void;onSaved?:(p:AudioProfile)=>void}){
  const [profile,setProfile]=useState<AudioProfile>(),[value,setValue]=useState(speechDefaults),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function refresh(){try{const p=await api<AudioProfile>('/api/audio/settings');setProfile(p);setValue({...speechDefaults,...p.defaults});setError('');}catch(e){setError(String(e));}}
  useEffect(()=>{void refresh();},[]);
  async function save(){setBusy(true);try{const p=await api<AudioProfile>('/api/audio/settings',{method:'PUT',body:JSON.stringify({revision:profile?.revision,defaults:value})});setProfile(p);onSaved?.(p);setError('');}catch(e){setError(String(e));}finally{setBusy(false);}}
  async function download(){try{const graph=await api<{api_graph:unknown}>('/api/audio/workflow');const url=URL.createObjectURL(new Blob([JSON.stringify(graph.api_graph,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='manju-indextts25-api.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){setError(String(e));}}
  return <Modal title="IndexTTS 2.5 · 人物配音" onClose={onClose} wide className="management-modal"><div className="video-advanced"><h3>角色音色与演绎</h3><p>用 2–30 秒清晰单人语音固定角色音色；可另外选择情绪参考，或用预设、文字指导表达。</p><p role="status">{profile?.ready?'本机已就绪 · 通过 ComfyUI 队列执行':profile?.errors.join('；')||'正在检查本机环境…'}</p><h3>新配音卡的默认参数</h3><SpeechControls value={value} disabled={busy} onChange={setValue} capabilities={profile?.capabilities}/><p>已有卡片保留自己的参数与固定参考版本。录音室质量使用 40 步声学合成，保留音量动态；附加停顿加在明确句界并保留自然句尾，不会消除逗号或呼吸停顿；请在多轨剪辑中检查时长。</p><p>生成结果保留为候选，可与音色、情绪原件对比试听后再采用。运行时不会上传音色或台词，人物外观图片不参与音色克隆。</p>{error&&<p role="alert" className="error">{error}</p>}<footer className="workflow-editor-footer"><button className="button secondary" onClick={()=>void refresh()}>检查可用性</button><button className="button secondary" onClick={()=>void download()}>导出 ComfyUI API 工作流</button><button className="button primary" disabled={busy||!profile} onClick={()=>void save()}>保存默认参数</button></footer></div></Modal>;
}
