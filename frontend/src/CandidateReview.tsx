import { useState } from "react";
import { createPortal } from "react-dom";
import { mediaUrl } from "./api";
import { Modal } from "./ui";
import type { ImageHistoryItem } from "./generationTypes";
import "./candidate-review.css";

export default function CandidateReview({current, preview, history, locked, onPreview, onAdopt, onContinue, onDiscard, onOpenImage}:{
 current?:string; preview?:string; history:ImageHistoryItem[]; locked?:boolean;
 onPreview:(id:string)=>void; onAdopt:(id:string)=>void; onContinue:(id:string)=>void; onDiscard:(id:string)=>void;
 onOpenImage:(id:string)=>void;
}) {
 const [compare,setCompare]=useState(false);
 const candidates=history.filter(item=>item.candidate && item.version_id!==current);
 const chosen=preview || candidates[0]?.version_id;
 return <div className="candidate-review nodrag nopan nowheel" onPointerDown={event=>event.stopPropagation()} onDoubleClick={event=>event.stopPropagation()}>
   <div className="candidate-thumbnails">{history.map((item,index)=><button key={item.version_id} className={item.version_id===chosen?"active":""} aria-label={"预览版本 "+(index+1)} onClick={()=>onPreview(item.version_id)}><img src={mediaUrl(item.version_id)} /><span>{item.version_id===current?"已采用":item.candidate?"候选":index+1}</span></button>)}</div>
   {chosen && <div className="candidate-actions"><button onClick={()=>onOpenImage(chosen)}>查看大图</button><button onClick={()=>setCompare(true)} disabled={!current}>新旧对比</button><button disabled={locked || chosen===current} onClick={()=>onAdopt(chosen)}>采用此版本</button><button disabled={locked} onClick={()=>onContinue(chosen)}>从此版本修改</button>{history.find(item=>item.version_id===chosen)?.candidate && chosen!==current && <button disabled={locked} onClick={()=>onDiscard(chosen)}>移除候选</button>}</div>}
   {preview && preview!==current && <button className="candidate-return" onClick={()=>current && onPreview(current)}>正在预览 · 返回已采用图片</button>}
   {compare && chosen && current && createPortal(<Modal title="新旧结果对比" wide onClose={()=>setCompare(false)}><div className="reference-compare"><figure><img src={mediaUrl(current,"preview")} /><figcaption>当前已采用</figcaption></figure><figure><img src={mediaUrl(chosen,"preview")} /><figcaption>当前预览版本</figcaption></figure></div><footer className="modal-footer"><button onClick={()=>setCompare(false)}>关闭</button><button disabled={locked || chosen===current} onClick={()=>{onAdopt(chosen);setCompare(false);}}>采用此版本</button></footer></Modal>,document.body)}
 </div>;
}
