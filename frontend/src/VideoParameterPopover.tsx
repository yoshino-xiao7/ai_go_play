import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { createPortal } from "react-dom";

// Portal keeps parameter menus outside the canvas composer's scrolling bounds.
export default function VideoParameterPopover({anchor,label,onClose,children,width=320}:{anchor:RefObject<HTMLButtonElement|null>;label:string;onClose:()=>void;children:ReactNode;width?:number}) {
  const panel=useRef<HTMLDivElement>(null),close=useRef(onClose);close.current=onClose;
  const [position,setPosition]=useState({left:12,top:12});
  const measure=()=>{
    const button=anchor.current?.getBoundingClientRect(),box=panel.current?.getBoundingClientRect();
    if(!button||!box)return;
    const left=Math.max(12,Math.min(window.innerWidth-box.width-12,button.right-box.width));
    const top=Math.max(12,Math.min(window.innerHeight-box.height-12,button.top-box.height-10>=12?button.top-box.height-10:button.bottom+10));
    setPosition(previous=>previous.left===left&&previous.top===top?previous:{left,top});
  };
  useLayoutEffect(measure);
  useEffect(()=>{
    const outside=(event:PointerEvent)=>{if(!panel.current?.contains(event.target as Node)&&!anchor.current?.contains(event.target as Node))close.current();};
    const key=(event:KeyboardEvent)=>{if(event.key==="Escape"){event.preventDefault();event.stopPropagation();close.current();anchor.current?.focus();}};
    const observer=new ResizeObserver(measure);if(panel.current)observer.observe(panel.current);
    window.addEventListener("resize",measure);window.addEventListener("scroll",measure,true);
    document.addEventListener("pointerdown",outside,true);document.addEventListener("keydown",key,true);
    panel.current?.querySelector<HTMLElement>("[aria-checked=true],input,button")?.focus({preventScroll:true});
    return()=>{observer.disconnect();window.removeEventListener("resize",measure);window.removeEventListener("scroll",measure,true);document.removeEventListener("pointerdown",outside,true);document.removeEventListener("keydown",key,true);};
  },[]);
  useEffect(()=>{
    const button=anchor.current;
    if(!button)return;
    const observer=new MutationObserver(()=>{
      if(!button.getClientRects().length || getComputedStyle(button).visibility==="hidden")close.current();
      else measure();
    });
    const container=button.closest(".canvas-card-controls");
    if(container)observer.observe(container,{attributes:true,attributeFilter:["style"]});
    const editor=button.closest(".card-control-editor");
    if(editor)observer.observe(editor,{attributes:true,attributeFilter:["style","hidden"]});
    return()=>observer.disconnect();
  },[anchor]);
  return createPortal(<div ref={panel} className="video-parameter-popover nodrag nopan nowheel" role="dialog" aria-label={label} style={{...position,width,maxWidth:"calc(100vw - 24px)"}} onPointerDown={e=>e.stopPropagation()} onWheel={e=>e.stopPropagation()} onKeyDown={e=>e.stopPropagation()}>{children}</div>,document.body);
}

export function VideoDuration({value,onChange,onBegin}:{value:number;onChange:(value:number)=>void;onBegin:()=>void}) {
  const [text,setText]=useState(String(value));
  useEffect(()=>setText(String(value)),[value]);
  const commit=()=>{const parsed=Number(text);const next=text.trim()&&Number.isFinite(parsed)?Math.max(4,Math.min(15,Math.round(parsed))):value;setText(String(next));onChange(next);};
  return <>
    <div className="video-popover-caption">选择视频生成时长</div>
    <div className="video-duration-row">
      <div className="video-duration-track">
        <input aria-label="视频时长滑杆" type="range" min={4} max={15} step={1} value={value} onPointerDown={onBegin} onKeyDown={onBegin} onChange={e=>onChange(Number(e.target.value))}/>
        <div className="video-duration-ticks">{[4,6,8,10,12,15].map(n=><span key={n} style={{left:((n-4)/11*100)+"%"}}>{n}</span>)}</div>
      </div>
      <label className="video-duration-number">
        <input aria-label="视频时长秒数" type="number" min={4} max={15} step={1} value={text} onFocus={onBegin} onChange={e=>{setText(e.target.value);const n=Number(e.target.value);if(e.target.value&&Number.isInteger(n)&&n>=4&&n<=15)onChange(n);}} onBlur={commit} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();commit();e.currentTarget.blur();}}}/><span>s</span>
      </label>
    </div>
    <p className="video-popover-footnote">本地 H3 支持 4–15 秒 · 实际约 {((Math.ceil((value*24-5)/17)*17+5)/24).toFixed(2)} 秒</p>
  </>;
}
