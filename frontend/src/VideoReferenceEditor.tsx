import {useEffect,useRef,useState} from "react";
import {createPortal} from "react-dom";
import {Modal} from "./ui";
import StudioSelect from "./StudioSelect";
import {api,mediaUrl} from "./api";
import type {ImageReference} from "./generationTypes";

const whole={x:0,y:0,width:1,height:1};
export default function VideoReferenceEditor({reference,width,height,onSave,onClose}:{reference:ImageReference;width:number;height:number;onSave:(ref:ImageReference)=>void;onClose:()=>void}){
  const [value,setValue]=useState({...reference,crop:reference.crop||whole,fit:reference.fit||"contain",purpose:reference.purpose||"general"} as ImageReference);
  const [duration,setDuration]=useState(0),[loadError,setLoadError]=useState("");
  const [variant,setVariant]=useState<"original"|"preview">("original");
  const canvas=useRef<HTMLCanvasElement>(null),player=useRef<HTMLVideoElement>(null),audio=useRef<HTMLAudioElement>(null);
  const crop=value.crop||whole,kind=reference.media_type||"image",frame=value.role==="first_frame"||value.role==="last_frame";
  const start=value.clip_start||0,end=value.clip_end??duration;
  const invalid=kind!=="image"&&(!duration||start<0||end>duration+.05||end-start<2||end-start>15.05);
  useEffect(()=>{if(kind==="image")return;let alive=true;void api<{version:{duration?:number}}>(`/api/versions/${reference.version_id}`).then(info=>{if(alive&&info.version.duration)setDuration(info.version.duration);}).catch(()=>{});return()=>{alive=false;};},[kind,reference.version_id]);
  useEffect(()=>{
    if(kind!=="image")return;
    let alive=true;const image=new Image();
    image.onload=()=>{
      const output=canvas.current;if(!alive||!output)return;
      const sw=image.naturalWidth*crop.width,sh=image.naturalHeight*crop.height;
      const target=frame?[width,height]:[sw,sh];const ratio=Math.min(640/target[0],360/target[1]);
      output.width=Math.max(1,Math.round(target[0]*ratio));output.height=Math.max(1,Math.round(target[1]*ratio));
      const ctx=output.getContext("2d");if(!ctx)return;
      ctx.fillStyle="#181818";ctx.fillRect(0,0,output.width,output.height);
      const scale=(frame&&value.fit==="cover"?Math.max:Math.min)(output.width/sw,output.height/sh);
      ctx.drawImage(image,image.naturalWidth*crop.x,image.naturalHeight*crop.y,sw,sh,(output.width-sw*scale)/2,(output.height-sh*scale)/2,sw*scale,sh*scale);
    };
    image.onerror=()=>setLoadError("原图读取失败，请关闭后重试。");image.src=mediaUrl(value.version_id,"original");
    return()=>{alive=false;};
  },[value.version_id,crop.x,crop.y,crop.width,crop.height,value.fit,width,height,frame,kind]);
  function changeCrop(key:keyof typeof whole,n:number){
    const next={...crop,[key]:n};next.x=Math.min(next.x,1-.01);next.y=Math.min(next.y,1-.01);
    next.width=Math.max(.01,Math.min(next.width,1-next.x));next.height=Math.max(.01,Math.min(next.height,1-next.y));setValue({...value,crop:next});
  }
  return createPortal(<Modal title={`参考素材 · ${reference.title}`} onClose={onClose} className="video-reference-editor">
    <div className="video-reference-editor-body">
      <label>参考用途<StudioSelect aria-label="参考用途" value={value.purpose} onChange={e=>setValue({...value,purpose:e.target.value as ImageReference["purpose"]})}>
        <option value="general">一般参考</option>{kind==="image"&&<><option value="identity">人物外貌与身份</option><option value="composition">场景与构图</option></>}{kind==="video"&&<option value="motion">动作与运镜</option>}{kind==="audio"&&<option value="voice">音色身份（按镜头重新演绎）</option>}
      </StudioSelect></label>
      {kind==="image"?<><div className="video-reference-crop-preview"><canvas ref={canvas} aria-label="实际输入构图预览"/></div>
        <div className="video-crop-presets">{[["完整图片",whole],["左侧人物",{x:0,y:0,width:1/3,height:1}],["中间人物",{x:1/3,y:0,width:1/3,height:1}],["右侧人物",{x:2/3,y:0,width:1/3,height:1}]].map(([label,region])=><button key={String(label)} onClick={()=>setValue({...value,crop:region as typeof whole})}>{String(label)}</button>)}</div>
        <div className="video-reference-crop-fields">{([['x','左侧'],['y','顶部'],['width','宽度'],['height','高度']] as const).map(([key,label])=><label key={key}>{label} %<input aria-label={`裁切${label}`} type="number" min={key==="x"||key==="y"?0:1} max={100} step={1} value={Math.round(crop[key]*1000)/10} onChange={e=>changeCrop(key,Math.max(0,Math.min(100,Number(e.target.value)))/100)}/></label>)}</div>
        {frame&&<label>适配视频画幅<StudioSelect aria-label="画幅适配" value={value.fit} onChange={e=>setValue({...value,fit:e.target.value as ImageReference["fit"]})}><option value="contain">完整保留 · 留边</option><option value="cover">填满画面 · 居中裁切</option></StudioSelect></label>}
        <p>预览展示实际裁切范围。三视图建议只选一个视角；人物参考描述会补入身份约束，但不能保证模型完全保持一致。</p>
      </>:<>
        {kind==="video"?<video ref={player} src={mediaUrl(value.version_id,variant)} controls muted={!value.use_audio} onLoadedMetadata={e=>{if(!duration)setDuration(e.currentTarget.duration);}} onTimeUpdate={e=>{if(end&&e.currentTarget.currentTime>=end)e.currentTarget.pause();}} onError={()=>{if(variant==="original")setVariant("preview");else setLoadError("浏览器暂时无法预览，可按原素材时长选择片段。");}}/>:<audio ref={audio} src={mediaUrl(value.version_id,variant)} controls onLoadedMetadata={e=>{if(!duration)setDuration(e.currentTarget.duration);}} onTimeUpdate={e=>{if(end&&e.currentTarget.currentTime>=end)e.currentTarget.pause();}} onError={()=>{if(variant==="original")setVariant("preview");else setLoadError("浏览器暂时无法试听，可按原素材时长选择片段。");}}/>}
        <div className="video-reference-crop-fields"><label>开始（秒）<input aria-label="片段开始" type="number" min={0} max={duration} step={.1} value={start} onChange={e=>setValue({...value,clip_start:Number(e.target.value)})}/></label><label>结束（秒）<input aria-label="片段结束" type="number" min={0} max={duration} step={.1} value={Math.round(end*100)/100} onChange={e=>setValue({...value,clip_end:Number(e.target.value)})}/></label></div>
        <button onClick={()=>{const element=player.current||audio.current;if(element){element.currentTime=start;void element.play().catch(()=>setLoadError("播放未成功，可按原素材时长选择片段。"));}}}>试听 / 播放所选片段</button>
        {kind==="video"&&<label className="video-reference-audio"><input type="checkbox" checked={!!value.use_audio} onChange={e=>setValue({...value,use_audio:e.target.checked})}/>同时参考视频原声</label>}
        <p>选择 2–15 秒。参考视频片段不能长于生成视频；参考原声与“生成声音”分别控制输入和输出。</p>
      </>}
      {loadError&&<p role="alert">{loadError}</p>}
      <footer><button className="button secondary" onClick={onClose}>取消</button><button className="button primary" disabled={invalid||(kind==="image"&&!!loadError)} onClick={()=>{onSave(kind==="image"?value:{...value,clip_start:start,clip_end:end});onClose();}}>应用到这次引用</button></footer>
    </div>
  </Modal>,document.body);
}
