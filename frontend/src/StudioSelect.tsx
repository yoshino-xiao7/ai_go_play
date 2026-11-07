import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { SelectHTMLAttributes } from "react";
import { createPortal } from "react-dom";
import { Check, Search } from "lucide-react";

type Option={value:string;label:string;disabled:boolean;group:string};

// Retain native select semantics, form values and change events; render the
// option surface in a portal so every existing field shares the same menu.
export default function StudioSelect(props:SelectHTMLAttributes<HTMLSelectElement>){
  const field=useRef<HTMLSelectElement>(null),panel=useRef<HTMLDivElement>(null),id=useId();
  const [open,setOpen]=useState(false),[options,setOptions]=useState<Option[]>([]),[query,setQuery]=useState(""),[active,setActive]=useState(0),[caption,setCaption]=useState("选择选项");
  const [position,setPosition]=useState({left:0,top:0,width:220});
  const filtered=options.filter(option=>option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const latest=useRef({filtered,active});latest.current={filtered,active};
  function show(){
    if(props.disabled||!field.current)return;
    const entries=Array.from(field.current.options).map(option=>({value:option.value,label:option.text,disabled:option.disabled||(option.parentElement instanceof HTMLOptGroupElement&&option.parentElement.disabled),group:option.parentElement instanceof HTMLOptGroupElement?option.parentElement.label:""}));
    const label=field.current.labels?.[0]?.cloneNode(true) as HTMLElement|undefined;label?.querySelectorAll('select,svg').forEach(node=>node.remove());
    setCaption(props['aria-label']||props.title||label?.textContent?.trim()||"选择选项");
    setOptions(entries);setQuery("");setActive(Math.max(0,entries.findIndex(option=>option.value===field.current!.value&&!option.disabled)));setOpen(true);field.current.focus();
  }
  function choose(option:Option){
    if(option.disabled||!field.current||field.current.disabled)return;
    field.current.value=option.value;
    field.current.dispatchEvent(new Event("change",{bubbles:true}));
    setOpen(false);field.current?.focus({preventScroll:true});
  }
  function measure(){
    const rect=field.current?.getBoundingClientRect(),box=panel.current?.getBoundingClientRect();if(!rect||!box)return;
    if(!rect.width||rect.bottom<0||rect.top>innerHeight||getComputedStyle(field.current!).visibility==="hidden"){setOpen(false);return;}
    const width=Math.min(Math.max(rect.width,220),420,innerWidth-24);
    const left=Math.max(12,Math.min(rect.left,innerWidth-width-12));
    const above=rect.top-box.height-8,below=rect.bottom+8;
    const prefersAbove=!!field.current?.closest('.generation-composer,.video-composer');
    const top=Math.max(12,Math.min(innerHeight-box.height-12,prefersAbove&&above>=12?above:below+box.height<=innerHeight-12?below:above));
    setPosition(old=>old.left===left&&old.top===top&&old.width===width?old:{left,top,width});
  }
  useLayoutEffect(()=>{if(open)measure();});
  useEffect(()=>{if(props.disabled)setOpen(false);},[props.disabled]);
  useEffect(()=>{
    if(!open)return;
    const nativeOptions=Array.from(field.current?.options||[]).map(option=>({option,hidden:option.getAttribute('aria-hidden')}));
    nativeOptions.forEach(({option})=>option.setAttribute('aria-hidden','true'));
    const outside=(event:PointerEvent)=>{if(event.target!==field.current&&!panel.current?.contains(event.target as Node))setOpen(false);};
    const key=(event:KeyboardEvent)=>{
      if(event.target!==field.current&&!panel.current?.contains(event.target as Node))return;
      const {filtered:items,active:index}=latest.current;
      if(event.key==="Escape"||event.key==="F4"){event.preventDefault();event.stopPropagation();setOpen(false);field.current?.focus({preventScroll:true});}
      else if(event.key==="Tab"){setOpen(false);field.current?.focus({preventScroll:true});}
      else if(["ArrowDown","ArrowUp","Home","End"].includes(event.key)&&(!(event.target instanceof HTMLInputElement)||event.key.startsWith("Arrow"))){
        event.preventDefault();event.stopPropagation();const enabled=items.map((option,i)=>option.disabled?-1:i).filter(i=>i>=0);if(!enabled.length)return;
        const cursor=enabled.indexOf(index),next=event.key==="Home"?enabled[0]:event.key==="End"?enabled.at(-1)!:cursor<0?(event.key==="ArrowDown"?enabled[0]:enabled.at(-1)!):enabled[(cursor+(event.key==="ArrowDown"?1:-1)+enabled.length)%enabled.length];setActive(next);
      }else if(event.key==="Enter"||(event.key===" "&&event.target===field.current)){event.preventDefault();event.stopPropagation();if(items[index])choose(items[index]);}
      else if(event.target===field.current&&event.key.length===1&&!event.ctrlKey&&!event.metaKey){event.preventDefault();const match=items.findIndex(option=>!option.disabled&&option.label.toLocaleLowerCase().startsWith(event.key.toLocaleLowerCase()));if(match>=0)setActive(match);}
    };
    const observer=new ResizeObserver(measure);if(panel.current)observer.observe(panel.current);if(field.current)observer.observe(field.current);
    document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',key,true);window.addEventListener('resize',measure);window.addEventListener('scroll',measure,true);
    return()=>{nativeOptions.forEach(({option,hidden})=>{if(hidden===null)option.removeAttribute('aria-hidden');else option.setAttribute('aria-hidden',hidden);});observer.disconnect();document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',key,true);window.removeEventListener('resize',measure);window.removeEventListener('scroll',measure,true);};
  },[open]);
  useEffect(()=>{if(open)panel.current?.querySelector(`[data-option-index="${active}"]`)?.scrollIntoView({block:"nearest"});},[open,active]);
  return <><select {...props} ref={field} className={`studio-select ${props.className||""}`} aria-expanded={open} aria-controls={open?id:undefined} aria-activedescendant={open&&filtered[active]?`${id}-${active}`:undefined}
    onMouseDown={event=>{props.onMouseDown?.(event);if(event.button===0&&!event.defaultPrevented&&!props.disabled){event.preventDefault();event.stopPropagation();if(open)setOpen(false);else show();}}}
    onClick={event=>{props.onClick?.(event);if(event.detail===0&&!props.disabled){event.preventDefault();show();}}}
    onKeyDown={event=>{props.onKeyDown?.(event);if(!event.defaultPrevented&&!open&&["ArrowDown","ArrowUp","Enter"," ","Home","End","F4"].includes(event.key)){event.preventDefault();event.stopPropagation();show();}}}
    onChange={event=>{props.onChange?.(event);setOpen(false);}}/>
    {open&&createPortal(<div ref={panel} className="studio-select-popup nodrag nopan nowheel" style={position} onPointerDown={event=>event.stopPropagation()} onWheel={event=>event.stopPropagation()}>
      <div className="studio-select-caption" title={caption}>{caption}</div>
      {options.length>8&&<label className="studio-select-search"><Search size={14}/><input aria-label="搜索选项" placeholder="搜索选项…" value={query} onChange={event=>{setQuery(event.target.value);setActive(0);}}/></label>}
      <div className="studio-select-options" id={id} role="listbox" aria-label={caption}>
        {filtered.map((option,index)=><div key={option.value+index}>{option.group&&(!index||filtered[index-1].group!==option.group)&&<div className="studio-select-group">{option.group}</div>}<button type="button" role="option" aria-selected={field.current?.value===option.value} aria-disabled={option.disabled} disabled={option.disabled} id={`${id}-${index}`} data-option-index={index} className={active===index?"is-highlighted":""} tabIndex={-1} title={option.label} onMouseDown={e=>e.preventDefault()} onMouseMove={()=>{if(!option.disabled)setActive(index);}} onClick={()=>choose(option)}><span>{option.label}</span>{field.current?.value===option.value&&<Check size={15}/>}</button></div>)}
        {!filtered.length&&<div className="studio-select-empty">没有匹配的选项</div>}
      </div>
    </div>,document.body)}
  </>;
}
