export type VideoDefaults = {width:number;height:number;steps:number;cfg:number;seed:number;duration:number;audio:boolean};
export type VideoProfile = {id?:string;kind?:"video";revision:number;ready:boolean;models:Record<string,string>;catalog:Record<string,string[]>;errors:string[];defaults:VideoDefaults;engines?:Record<string,{ready:boolean;errors:string[]}>};
export const videoModelNames:Record<string,string>={fl2va:"文生 / 首尾帧模型",ref2va:"全参考模型",clip:"文本编码器",video_vae:"视频 VAE",audio_vae:"音频 VAE"};
export const videoModeNames={text:"文生视频",frames:"首尾帧",reference:"全参考"};
export const videoEngines={
  native:{label:"原生基线",short:"原生",description:"官方节点 · 独立镜头"},
  director:{label:"Director",short:"Director",description:"社区外接组 · 一张卡对应一个镜头"},
  turbo:{label:"Turbo 8 步全能参考",short:"Turbo 8 步",description:"Euler / beta · step600 EMA · 原生音视频"},
} as const;
export function videoModelMatches(key:string,value:string){return /h3/i.test(value)&&(key==="fl2va"?/fl2va|hybrid/i.test(value):key==="ref2va"?/ref2va|hybrid/i.test(value):key==="video_vae"?/video/i.test(value):key==="audio_vae"?/audio/i.test(value):/qwen/i.test(value));}
