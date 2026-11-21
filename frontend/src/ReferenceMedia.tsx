import {lazy,Suspense,useEffect,useState} from "react";
import type {ReactNode} from "react";
import {createPortal} from "react-dom";
import {ArrowLeft,ArrowRight,Film,Music2,X} from "lucide-react";
import type {ImageReference} from "./generationTypes";
import {mediaUrl} from "./api";
import {Modal} from "./ui";
import ImageViewer from "./ImageViewer";

const VideoViewer=lazy(()=>import("./VideoViewer"));
type Hover=(reference:ImageReference,rect:DOMRect|null)=>void;
type Preview={reference:ImageReference;rect:DOMRect};

export function ReferenceTile({reference,index,badge,disabled,onHover,onOpen,onRemove,onMove,canMoveBack=true,canMoveForward=true,children}:{
  reference:ImageReference;index:number;badge?:string;disabled?:boolean;onHover:Hover;onOpen:(reference:ImageReference)=>void;
  onRemove?:()=>void;onMove?:(direction:number)=>void;canMoveBack?:boolean;canMoveForward?:boolean;children?:ReactNode;
}){
  const kind=reference.media_type||"image";
  return <div className="generation-reference reference-tile" data-version-id={reference.version_id}>
    <button type="button" className="studio-reference-image" aria-label={`预览参考素材 ${reference.title}`}
      onMouseEnter={e=>onHover(reference,e.currentTarget.getBoundingClientRect())} onMouseLeave={()=>onHover(reference,null)}
      onClick={()=>onOpen(reference)}>
      {kind==="audio"?<Music2 className="reference-audio-icon" size={28}/>:<img src={mediaUrl(reference.version_id)} alt={reference.title}/>}
      <span className="generation-reference-index">{index+1}</span>
      {kind==="video"&&<Film className="reference-kind-icon" size={15}/>}
    </button>
    {badge&&<span className="studio-reference-base">{badge}</span>}
    {(onMove||onRemove)&&<div className="generation-reference-actions">
      {onMove&&<>
        <button type="button" title="参考素材前移" aria-label="参考素材前移" disabled={disabled||!canMoveBack} onClick={()=>onMove(-1)}><ArrowLeft size={13}/></button>
        <button type="button" title="参考素材后移" aria-label="参考素材后移" disabled={disabled||!canMoveForward} onClick={()=>onMove(1)}><ArrowRight size={13}/></button>
      </>}
      {onRemove&&<button type="button" className="studio-remove-reference" title="移除引用"
        aria-label={`移除引用 ${reference.title}`} disabled={disabled} onClick={()=>{onHover(reference,null);onRemove();}}>
        <X size={13}/>
      </button>}
    </div>}
    {children&&<div className="reference-tile-status">{children}</div>}
  </div>;
}

function ReferenceHover({preview,references}:{preview:Preview;references:ImageReference[]}){
  const {reference,rect}=preview,kind=reference.media_type||"image";
  const width=Math.min(264,innerWidth-24),height=Math.min(225,Math.max(80,innerHeight-110)),total=height+58;
  const top=rect.top-total-10>=12?rect.top-total-10:rect.bottom+total+10<=innerHeight-12?rect.bottom+10:Math.max(12,innerHeight-total-12);
  const index=references.findIndex(item=>item.version_id===reference.version_id);
  const source=reference.source==="connection"?"来自连线":reference.source==="base"?"编辑底图":"固定素材引用";
  return createPortal(<div className="studio-reference-preview reference-media-preview" role="tooltip" style={{width,left:Math.max(12,Math.min(rect.left,innerWidth-width-12)),top}}>
    {kind==="audio"?<div className="reference-audio-poster"><Music2 size={32}/><span>点击试听音频</span></div>:<img style={{maxHeight:height}} src={mediaUrl(reference.version_id,kind==="image"?"original":"thumbnail")} alt={reference.title}/>}
    <div><strong>{reference.title}</strong><span>{({image:"图",video:"视频",audio:"音频"})[kind]} {index<0?"":index+1} · {source} · 点击{kind==="image"?"查看大图":kind==="video"?"播放":"试听"}</span></div>
  </div>,document.body);
}

function AudioPreview({reference,onClose}:{reference:ImageReference;onClose:()=>void}){
  const [variant,setVariant]=useState("original"),[failed,setFailed]=useState(false);
  return createPortal(<div className="reference-audio-dialog nodrag nopan nowheel" onPointerDown={e=>e.stopPropagation()} onKeyDown={e=>{if(e.key==="Escape"){e.stopPropagation();onClose();}}}>
    <Modal title="音频参考预览" onClose={onClose}><div className="reference-audio-content"><Music2 size={48}/><strong>{reference.title}</strong>{failed?<p role="alert">浏览器无法播放此音频，可下载原件查看。</p>:<audio src={mediaUrl(reference.version_id,variant)} controls preload="metadata" onError={()=>{if(variant==="original")setVariant("preview");else setFailed(true);}}/>}<a href={mediaUrl(reference.version_id,"original",true)} download>下载原件</a></div></Modal>
  </div>,document.body);
}

export function useReferencePreview(){
  const [referencePreview,setReferencePreview]=useState<Preview|null>(null),[opened,setOpened]=useState<ImageReference|null>(null);
  const hoverReference:Hover=(reference,rect)=>setReferencePreview(rect?{reference,rect}:null);
  function openReference(reference:ImageReference){setReferencePreview(null);setOpened(reference);}
  useEffect(()=>{
    const clear=()=>setReferencePreview(null),key=(e:KeyboardEvent)=>{if(e.key==="Escape")clear();};
    window.addEventListener("resize",clear);window.addEventListener("scroll",clear,true);window.addEventListener("blur",clear);document.addEventListener("keydown",key);
    return()=>{window.removeEventListener("resize",clear);window.removeEventListener("scroll",clear,true);window.removeEventListener("blur",clear);document.removeEventListener("keydown",key);};
  },[]);
  function renderReferencePreview(references:ImageReference[]){
    const kind=opened?.media_type||"image";
    return <>{referencePreview&&!opened&&<ReferenceHover preview={referencePreview} references={references}/>}{opened&&<Suspense fallback={null}>{kind==="image"?<ImageViewer versionId={opened.version_id} versions={[opened.version_id]} onClose={()=>setOpened(null)}/>:kind==="video"?<VideoViewer versionId={opened.version_id} onClose={()=>setOpened(null)}/>:<AudioPreview reference={opened} onClose={()=>setOpened(null)}/>}</Suspense>}</>;
  }
  return {setReferencePreview,hoverReference,openReference,renderReferencePreview};
}
