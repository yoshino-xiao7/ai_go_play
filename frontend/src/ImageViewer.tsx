import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { mediaUrl } from "./api";
import { Modal } from "./ui";
import CandidateReview from "./CandidateReview";
import type { ImageReview } from "./CandidateReview";
import "./image-viewer.css";

export default function ImageViewer({versionId, versions, review, onClose}:{
 versionId:string; versions:string[]; review?:ImageReview; onClose:()=>void;
}) {
 const [selected,setSelected]=useState(versionId);
 const [compare,setCompare]=useState(false);
 const [size,setSize]=useState({width:0,height:0});
 const [view,setView]=useState({scale:1,x:0,y:0});
 const [failed,setFailed]=useState(false);
 const surface=useRef<HTMLDivElement>(null);
 const drag=useRef<{id:number;x:number;y:number;originX:number;originY:number}|null>(null);
 const current=versions.includes(selected) ? selected : review?.adopted || versions[0] || versionId;
 const index=versions.indexOf(current);
 const comparing=!!(compare && review?.adopted && review.adopted!==current);
 const select=(id:string)=>{
  setSelected(id);
  if(id===review?.adopted)setCompare(false);
 };
 const step=(delta:number)=>{
  const next=versions[index+delta];
  if(index>=0 && next)select(next);
 };
 const fit=()=>{
  const box=surface.current?.getBoundingClientRect();
  if(box && box.width>32 && box.height>32 && size.width) setView({scale:Math.min((box.width-32)/size.width,(box.height-32)/size.height,1),x:0,y:0});
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
 return createPortal(<div className="image-viewer-shell" onKeyDown={event=>{
   if(event.key==="Escape"){event.stopPropagation();event.preventDefault();onClose();}
   if(!event.altKey && !event.ctrlKey && !event.metaKey && (event.key==="ArrowLeft" || event.key==="ArrowRight")){
    event.stopPropagation();event.preventDefault();step(event.key==="ArrowLeft" ? -1 : 1);
   }
  }} onDoubleClick={event=>event.stopPropagation()} onPointerDown={event=>event.stopPropagation()}
  onClick={event=>event.stopPropagation()} onDragStart={event=>{event.preventDefault();event.stopPropagation();}}>
  <Modal title={review && versions.length>1 ? "图片版本预览" : "图片大图预览"} onClose={onClose} wide>
   <div className="image-viewer-toolbar">
    {versions.length>1 && <>
     <button disabled={index<=0} onClick={()=>step(-1)}>上一张</button>
     <span aria-live="polite">版本 {index+1} / {versions.length}</span>
     <button disabled={index<0 || index>=versions.length-1} onClick={()=>step(1)}>下一张</button>
    </>}
    <button disabled={comparing} onClick={()=>zoom(1/1.25)} aria-label="预览缩小">−</button>
    <output>{Math.round(view.scale*100)}%</output>
    <button disabled={comparing} onClick={()=>zoom(1.25)} aria-label="预览放大">＋</button>
    <button disabled={comparing} onClick={()=>setView({scale:1,x:0,y:0})}>原始尺寸 100%</button>
    <button disabled={comparing} onClick={fit}>适应窗口</button>
    <a href={mediaUrl(current,"original")} download draggable={false}>下载原图</a>
   </div>
   {comparing && <div className="image-viewer-compare">
    <figure><img src={mediaUrl(review!.adopted!,"preview")} alt="当前已采用图片" draggable={false} /><figcaption>已采用</figcaption></figure>
    <figure><img src={mediaUrl(current,"preview")} alt="正在预览的图片" draggable={false} /><figcaption>版本 {index+1} · 正在预览</figcaption></figure>
   </div>}
   <div ref={surface} hidden={comparing} className="image-viewer-surface" onPointerDown={e=>{
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
   <footer className="image-viewer-footer">
    {size.width>0 && <span>{size.width} × {size.height} · 原图{view.scale>1 && !comparing ? " · 超过 100% 为像素放大" : ""}</span>}
    <span>{versions.length>1 ? "← → 切换版本 · " : ""}{comparing ? "" : "滚轮缩放 · 拖动查看细节 · "}Esc 关闭</span>
   </footer>
   {review && (versions.length>1 || !review.adopted) && <CandidateReview
    review={review} selected={current} comparing={comparing} onSelect={select} onCompare={()=>setCompare(!comparing)} />}
  </Modal>
 </div>,document.body);
}
