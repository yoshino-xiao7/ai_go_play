import { useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, X } from "lucide-react";
import { mediaUrl } from "./api";
import type { ProductionSettings, ProductionShot } from "./productionTypes";

const timecode = (n: number) => `${Math.floor(n / 60).toString().padStart(2, "0")}:${(n % 60).toFixed(1).padStart(4, "0")}`;
const interrupted = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

// Keep the implicit subtitle window identical to production.subtitle_entries.
export function subtitleWindow(shot: ProductionShot, audioDuration?: number) {
  const start = shot.subtitle_start ?? (shot.audio_version_id ? shot.audio_offset : 0);
  return { start, end: shot.subtitle_end ?? Math.min(shot.duration, start + (audioDuration || shot.audio_duration || shot.duration)) };
}

export default function ProductionPreview({ shots, settings, onClose }: { shots: ProductionShot[]; settings: ProductionSettings; onClose: () => void }) {
  const [index, setIndex] = useState(0), [playing, setPlaying] = useState(true), [elapsed, setElapsed] = useState(0);
  const [variant, setVariant] = useState("original"), [error, setError] = useState(""), [audioDuration, setAudioDuration] = useState<number>();
  const video = useRef<HTMLVideoElement>(null), audio = useRef<HTMLAudioElement>(null), background = useRef<HTMLAudioElement>(null);
  const context = useRef<AudioContext | null>(null);
  const routes = useRef(new Map<HTMLMediaElement, { source: MediaElementAudioSourceNode; gain: GainNode }>());
  const playingRef = useRef(playing); playingRef.current = playing;
  const advancing = useRef(false);
  const shot = shots[index], start = shots.slice(0, index).reduce((sum, item) => sum + item.duration, 0);

  const volume = useCallback((element: HTMLMediaElement, value: number) => {
    try {
      const ctx = context.current ||= new AudioContext();
      let route = routes.current.get(element);
      if (!route) {
        route = { source: ctx.createMediaElementSource(element), gain: ctx.createGain() };
        route.source.connect(route.gain); route.gain.connect(ctx.destination); routes.current.set(element, route);
      }
      // HTMLMediaElement.volume cannot represent the supported 100–200% gain.
      element.volume = 1; route.gain.gain.value = Math.max(0, Math.min(2, value));
      if (ctx.state === "suspended") void ctx.resume().catch(() => setError("点击播放以启用预览声音。"));
    } catch {
      element.volume = Math.max(0, Math.min(1, value));
      if (value > 1) setError("此浏览器不支持音量增强，预览音量上限为 100%；导出仍按设置混音。");
    }
  }, []);

  const sync = useCallback((local: number, shouldPlay: boolean) => {
    const sound = audio.current;
    if (sound) {
      volume(sound, shot.audio_volume);
      const target = local - shot.audio_offset;
      if (target >= 0 && (!Number.isFinite(sound.duration) || target < sound.duration)) {
        if (Math.abs(sound.currentTime - target) > .12) sound.currentTime = target;
        if (shouldPlay && sound.paused) void sound.play().catch(error => { if (!interrupted(error)) setError("配音未能播放，请再次点击播放。"); });
        if (!shouldPlay) sound.pause();
      } else { sound.pause(); if (target < 0 && sound.currentTime) sound.currentTime = 0; }
    }
    const music = background.current;
    if (music) {
      volume(music, settings.background_volume);
      const target = Number.isFinite(music.duration) && music.duration > 0 ? (start + local) % music.duration : 0;
      if (Math.abs(music.currentTime - target) > .12) music.currentTime = target;
      if (shouldPlay && music.paused) void music.play().catch(error => { if (!interrupted(error)) setError("配乐未能播放，请再次点击播放。"); });
      if (!shouldPlay) music.pause();
    }
  }, [shot, start, settings.background_volume, volume]);

  const goTo = useCallback((next: number) => {
    advancing.current = true; video.current?.pause(); audio.current?.pause(); background.current?.pause();
    setElapsed(0); setAudioDuration(undefined); setError(""); setVariant("original");
    setIndex(next); setPlaying(true);
  }, []);
  const advance = useCallback(() => {
    if (advancing.current) return;
    advancing.current = true; video.current?.pause(); audio.current?.pause(); background.current?.pause();
    setElapsed(shot.duration);
    if (index + 1 < shots.length) goTo(index + 1);
    else setPlaying(false);
  }, [goTo, index, shot.duration, shots.length]);

  const update = useCallback(() => {
    const element = video.current;
    if (!element || advancing.current) return;
    const local = Math.max(0, element.currentTime - shot.trim_start);
    setElapsed(Math.min(local, shot.duration));
    if (local >= shot.duration - .005) advance();
    else sync(local, playingRef.current && !element.paused && !element.seeking && element.readyState >= 3);
  }, [advance, shot.duration, shot.trim_start, sync]);

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (playing) void element.play().catch(error => { if (!interrupted(error) && !element.error) setPlaying(false); });
    else { element.pause(); sync(Math.max(0, element.currentTime - shot.trim_start), false); }
  }, [playing, index, shot.trim_start, sync]);
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => { update(); frame = requestAnimationFrame(tick); };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, update]);
  const release = useCallback((element: HTMLMediaElement | null) => {
    if (!element) return;
    element.pause();
    const route = routes.current.get(element);
    route?.source.disconnect(); route?.gain.disconnect(); routes.current.delete(element);
    element.removeAttribute("src"); element.load();
  }, []);
  useEffect(() => {
    const element = video.current;
    return () => release(element);
  }, [index, variant, release]);
  useEffect(() => {
    const element = audio.current;
    return () => release(element);
  }, [index, release]);
  useEffect(() => () => {
    for (const [element, route] of routes.current) { element.pause(); route.source.disconnect(); route.gain.disconnect(); }
    routes.current.clear();
    if (context.current) void context.current.close();
    context.current = null;
  }, []);

  const subtitles = subtitleWindow(shot, audioDuration), dialogue = shot.dialogue.trim();
  return <section className="production-player" aria-label="分镜连续预览">
    <header><strong>{index + 1} / {shots.length} · {shot.title}</strong><button aria-label="结束连续预览" onClick={onClose}><X size={18}/></button></header>
    <div className="production-player-picture" style={{ aspectRatio: `${settings.width}/${settings.height}` }}>
      <video ref={video} key={`${index}-${variant}`} src={mediaUrl(shot.video_version_id!, variant)} playsInline preload="auto" poster={mediaUrl(shot.video_version_id!)}
        onLoadedMetadata={e => { const element = e.currentTarget; advancing.current = false; element.currentTime = shot.trim_start; volume(element, shot.video_volume); if (playingRef.current) void element.play().catch(error => { if (!interrupted(error) && !element.error) setPlaying(false); }); }}
        onPlaying={update} onSeeking={() => sync(elapsed, false)} onSeeked={update}
        onWaiting={() => sync(elapsed, false)} onTimeUpdate={update}
        onEnded={advance} onError={() => { sync(elapsed, false); if (variant === "original") setVariant("preview"); else { setError("此镜头暂时无法播放，请检查素材原件。"); setPlaying(false); } }}/>
      {dialogue && elapsed >= subtitles.start && elapsed < subtitles.end && <div className="production-subtitle">{dialogue}</div>}
      {shot.audio_version_id && <audio ref={audio} key={`${index}-${shot.audio_version_id}`} src={mediaUrl(shot.audio_version_id, "original")} preload="auto" onLoadedMetadata={e => { setAudioDuration(e.currentTarget.duration); update(); }} onError={() => setError("配音无法播放，请检查音频原件。")}/>}
      {settings.background_audio_version_id && <audio ref={background} src={mediaUrl(settings.background_audio_version_id, "original")} loop preload="auto" onLoadedMetadata={update} onError={() => setError("配乐无法播放，请检查音频原件。")}/>}
    </div>
    <div className="production-player-controls"><button onClick={() => {
      if (advancing.current && index === shots.length - 1) {
        goTo(0);
        if (index === 0 && video.current) { advancing.current = false; video.current.currentTime = shot.trim_start; void video.current.play().catch(() => setPlaying(false)); }
      } else setPlaying(!playing);
    }} aria-label={playing ? "暂停预览" : "播放预览"}>{playing ? <Pause size={17}/> : <Play size={17}/>}</button><span>{timecode(start + elapsed)} / {timecode(shots.reduce((sum, item) => sum + item.duration, 0))}</span><progress value={elapsed} max={shot.duration}/><button disabled={index === 0} onClick={() => goTo(index - 1)}>上一镜</button><button disabled={index === shots.length - 1} onClick={() => goTo(index + 1)}>下一镜</button></div>
    {error && <p className="production-error" role="alert">{error}</p>}
    <p className="production-hint">按已采用的版本、裁剪、字幕时间和音量连播；精确切镜与混音限幅以导出成片为准。</p>
  </section>;
}
