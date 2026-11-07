import { useState } from "react";
import { Pencil, Check, X } from "lucide-react";

export default function SubjectInlineText({value,kind,placeholder,locked,onSave}:{value:string;kind:"name"|"description";placeholder:string;locked?:boolean;onSave:(text:string)=>void}) {
 const [editing,setEditing]=useState(false);
 const [draft,setDraft]=useState(value);
 const save=()=>{if(locked || kind==="name" && !draft.trim())return;onSave(kind==="name"?draft.trim():draft);setEditing(false);};
 const cancel=()=>{setDraft(value);setEditing(false);};
 const key=(event:React.KeyboardEvent)=>{if(event.nativeEvent.isComposing)return;if(event.key==="Escape"){event.preventDefault();event.stopPropagation();cancel();}else if(event.key==="Enter"&&(kind==="name"||event.ctrlKey)){event.preventDefault();save();}};
 if(editing && !locked) return <div className="subject-inline-edit nodrag nopan nowheel" onPointerDown={event=>event.stopPropagation()} onDoubleClick={event=>event.stopPropagation()}>
  {kind==="name"?<input autoFocus aria-label="主体名称" maxLength={250} value={draft} onChange={event=>setDraft(event.target.value)} onKeyDown={key}/>:<textarea autoFocus aria-label="主体描述" maxLength={6000} value={draft} onChange={event=>setDraft(event.target.value)} onKeyDown={key}/>}
  <div><button aria-label="确认主体编辑" onClick={save}><Check size={13}/></button><button aria-label="取消主体编辑" onClick={cancel}><X size={13}/></button></div>
 </div>;
 return <button className={(kind==="name"?"subject-node-name":"subject-node-description")+(value?"":" empty")+" nodrag nopan"} disabled={locked} title={value||placeholder} aria-label={kind==="name"?"编辑主体名称":"编辑主体描述"} onPointerDown={event=>event.stopPropagation()} onDoubleClick={event=>event.stopPropagation()} onClick={()=>{setDraft(value);setEditing(true);}}>
 {kind==="name"?<><span className="subject-at">@</span><strong>{value}</strong><Pencil size={14}/></>:value||placeholder}
 </button>;
}
