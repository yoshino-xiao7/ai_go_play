import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { mediaUrl } from "./api";
import { Modal } from "./ui";
import "./image-viewer.css";

export default function ImageViewer({versionId, versions, onClose}:{
 versionId:string; versions:string[]; onClose:()=>void;
}) {
 const [current,setCurrent]=useState(versionId);
 const [size,setSize]=useState({width:0,height:0});
 const [view,setView]=useState({scale:1,x:0,y:0});
 const [failed,setFailed]=useState(false);
 const surface=useRef<HTMLDivElement>(null);
 const drag=useRef<{id:number;x:number;y:number;originX:number;originY:number}|null>(null);
 const index=versions.indexOf(current);
 const fit=()=>{
  const box=surface.current?.getBoundingClientRect();
  if(box && size.width) setView({scale:Math.min((box.width-32)/size.width,(box.height-32)/size.height,1),x:0,y:0});
 };
 useEffect(()=>{
  setSize({width:0,height:0});setFailed(false);setView({scale:1,x:0,y:0});
 },[current]);
 useEffect(()=>{
  fit();
  const observer=new ResizeObserver(fit);
  if(surface.current)observer.observe(surface.current);
  return()=>observer.disconnect();
 },[size.width,size.height]);
 const zoom=(factor:number,point?:{x:number;y:number})=>setView(old=>{
  const scale=Math.max(.02,Math.min(8,old.scale*factor)),ratio=scale/old.scale;
  return {scale,x:point?point.x-(point.x-old.x)*ratio:old.x*ratio,y:point?point.y-(point.y-old.y)*ratio:old.y*ratio};
 });
 useEffect(()=>{
  const element=surface.current;
  if(!element)return;
  const wheel=(event:WheelEvent)=>{
   event.preventDefault();event.stopPropagation();
   const rect=element.getBoundingClientRect();
   zoom(Math.exp(-event.deltaY*.002),{x:event.clientX-rect.left-rect.width/2,y:event.clientY-rect.top-rect.height/2});
  };
  element.addEventListener("wheel",wheel,{passive:false});
  return()=>element.removeEventListener("wheel",wheel);
 },[]);
 return createPortal(<div className="image-viewer-shell" onKeyDown={e=>{if(e.key==="Escape"){e.stopPropagation();e.preventDefault();onClose();}}} onDoubleClick={e=>e.stopPropagation()} onPointerDown={e=>e.stopPropagation()}>
  <Modal title="图片大图预览" onClose={onClose} wide>
   <div className="image-viewer-toolbar">
    <button disabled={index<=0} onClick={()=>setCurrent(versions[index-1])}>上一张</button>
    <span>{index+1} / {versions.length}</span>
    <button disabled={index<0 || index>=versions.length-1} onClick={()=>setCurrent(versions[index+1])}>下一张</button>
    <button onClick={()=>zoom(1/1.25)} aria-label="预览缩小">−</button>
    <output>{Math.round(view.scale*100)}%</output>
    <button onClick={()=>zoom(1.25)} aria-label="预览放大">＋</button>
    <button onClick={()=>setView({scale:1,x:0,y:0})}>原始尺寸 100%</button>
    <button onClick={fit}>适应窗口</button>
    <a href={mediaUrl(current,"original")} download>下载原图</a>
   </div>
   <div ref={surface} className="image-viewer-surface" onPointerDown={e=>{
    if(e.button!==0)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);
    drag.current={id:e.pointerId,x:e.clientX,y:e.clientY,originX:view.x,originY:view.y};
   }} onPointerMove={e=>{const d=drag.current;if(d?.id===e.pointerId)setView(old=>({...old,x:d.originX+e.clientX-d.x,y:d.originY+e.clientY-d.y}));}}
   onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onLostPointerCapture={()=>{drag.current=null;}}>
    {!size.width && !failed && <span className="image-viewer-message">正在加载原图…</span>}
    {failed ? <span className="image-viewer-message" role="alert">原图暂时无法读取，请检查资产文件。</span> :
    <img key={current} className="image-viewer-original" src={mediaUrl(current,"original")} alt="原始图片预览" draggable={false}
     onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})} onError={()=>setFailed(true)}
     style={{width:size.width||undefined,height:size.height||undefined,visibility:size.width?"visible":"hidden",left:"calc(50% + "+view.x+"px)",top:"calc(50% + "+view.y+"px)",transform:"translate(-50%, -50%) scale("+view.scale+")"}}/>}
   </div>
   <footer className="image-viewer-footer">{size.width>0 && <span>{size.width} × {size.height} · 原图{view.scale>1 ? " · 超过 100% 为像素放大，不会增加细节" : ""}</span>}<span>滚轮缩放 · 左键拖动查看细节 · Esc 关闭</span></footer>
  </Modal>
 </div>,document.body);
}
