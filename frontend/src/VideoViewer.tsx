import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, X } from "lucide-react";
import { mediaUrl } from "./api";

export default function VideoViewer({versionId, versions = [], onClose,kind="video"}: {versionId:string;kind?:"video"|"audio"; versions?:string[]; onClose:()=>void}) {
  const [current,setCurrent]=useState(versionId);
  const [variant,setVariant]=useState("original"),[failed,setFailed]=useState(false),[info,setInfo]=useState("");
  const dialog=useRef<HTMLDivElement>(null),closeRef=useRef(onClose);closeRef.current=onClose;
  useEffect(()=>{setVariant("original");setFailed(false);setInfo("");},[current]);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;const key=(event:KeyboardEvent)=>{if(event.key==="Escape"){event.stopPropagation();closeRef.current();}if(event.key==="Tab"){const entries=Array.from(dialog.current?.querySelectorAll<HTMLElement>("a[href],button,video,audio")||[]);const first=entries[0],last=entries[entries.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};document.addEventListener("keydown",key,true);return()=>{document.removeEventListener("keydown",key,true);previous?.focus();};},[]);
  return createPortal(<div ref={dialog} className="video-viewer nodrag nopan nowheel" role="dialog" aria-modal="true" aria-label={kind==="audio"?"配音原件预览":"视频原件预览"} onKeyDown={e=>e.stopPropagation()} onPointerDown={e=>e.stopPropagation()} onDoubleClick={e=>e.stopPropagation()}>
    <header><strong>{variant==="original"?(kind==="audio"?"配音原件":"视频原件"):"兼容预览"}</strong><span>{info} · {kind==="audio"?"可拖动进度、调节音量":"可拖动进度、调节音量或全屏"}</span><a href={mediaUrl(current,"original",true)} download title="下载原件"><Download size={18}/></a><button autoFocus onClick={onClose} aria-label={kind==="audio"?"关闭配音预览":"关闭视频预览"}><X/></button></header>
    {failed?<p role="alert">浏览器暂时无法播放此版本，可下载原件查看。</p>:kind==="audio"?<div className="audio-viewer-content"><img src={mediaUrl(current,"waveform")} alt="配音波形"/><audio key={current+variant} src={mediaUrl(current,variant)} controls autoPlay preload="metadata" onLoadedMetadata={e=>setInfo(`${e.currentTarget.duration.toFixed(2)} 秒`)} onError={()=>{if(variant==="original")setVariant("preview");else setFailed(true);}}/></div>:<video key={current+variant} src={mediaUrl(current,variant)} controls autoPlay playsInline preload="metadata" onLoadedMetadata={e=>setInfo(`${e.currentTarget.videoWidth} × ${e.currentTarget.videoHeight} · ${e.currentTarget.duration.toFixed(2)} 秒`)} onError={()=>{if(variant==="original")setVariant("preview");else setFailed(true);}}/>}
    {versions.length>1&&<nav>{versions.map((id,index)=><button key={id} className={id===current?"active":""} onClick={()=>setCurrent(id)}>版本 {index+1}</button>)}</nav>}
  </div>,document.body);
}
