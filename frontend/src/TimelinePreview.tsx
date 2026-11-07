import { useCallback, useEffect, useRef, useState } from "react";
import { mediaUrl } from "./api";
import type { AssetVersion } from "./types";
import { clipGain, timelineDuration, type TimelineClip, type TimelineEdit } from "./timelineTypes";

type Route = { source: MediaElementAudioSourceNode; gain: GainNode; high: BiquadFilterNode; high2: BiquadFilterNode; low: BiquadFilterNode; equalizer: BiquadFilterNode; compressor: DynamicsCompressorNode; preset?: TimelineClip["audio_preset"] };
type MediaProps = { clip: TimelineClip; kind: "video" | "audio"; local: number; playing: boolean; setVolume: (element: HTMLMediaElement, value: number, preset?: TimelineClip["audio_preset"]) => void; release: (element: HTMLMediaElement) => void; onError: (message: string) => void };

function MediaLayer({ clip, kind, local, playing, setVolume, release, onError }: MediaProps) {
  const media = useRef<HTMLMediaElement | null>(null);
  const [variant, setVariant] = useState("original");
  const latest = useRef({ clip, local, playing }); latest.current = { clip, local, playing };
  const bind = useCallback((element: HTMLMediaElement | null) => {
    if (media.current && media.current !== element) release(media.current);
    media.current = element;
  }, [release]);
  const sync = useCallback(() => {
    const element = media.current, state = latest.current;
    if (!element) return;
    const target = state.clip.trim_start + Math.max(0, state.local);
    setVolume(element, state.clip.volume * clipGain(state.clip, state.local), state.clip.audio_preset);
    if (element.readyState >= 1 && Math.abs(element.currentTime - target) > .12) element.currentTime = target;
    if (state.playing && element.paused) void element.play().catch(error => {
      if (error?.name !== "AbortError" && !element.error) onError("浏览器尚未播放声音，请暂停后重新播放。");
    });
    if (!state.playing) element.pause();
  }, [onError, setVolume]);
  useEffect(sync, [local, playing, clip, sync]);
  const props = {
    src: mediaUrl(clip.asset_version_id!, variant), preload: "auto", onLoadedMetadata: sync,
    onError: () => { if (variant === "original") setVariant("preview"); else onError("有片段无法预览，请检查原始素材；时间线编辑已保留。"); },
  };
  return kind === "audio" ? <audio {...props} ref={bind}/> : <video {...props} ref={bind} playsInline/>;
}

export default function TimelinePreview({ edit, versions, time, playing, onTime, onPlayingChange }: { edit: TimelineEdit; versions: Record<string, AssetVersion>; time: number; playing: boolean; onTime: (value: number) => void; onPlayingChange: (value: boolean) => void }) {
  const stage = useRef<HTMLDivElement>(null), [scale, setScale] = useState(1), [error, setError] = useState("");
  const context = useRef<AudioContext | null>(null), routes = useRef(new Map<HTMLMediaElement, Route>());
  const state = useRef({ time, onTime, onPlayingChange }); state.current = { time, onTime, onPlayingChange };
  const duration = timelineDuration(edit);
  useEffect(() => {
    const element = stage.current;
    if (!element) return;
    const resize = () => setScale(Math.min(element.clientWidth / edit.settings.width, element.clientHeight / edit.settings.height));
    resize(); const observer = new ResizeObserver(resize); observer.observe(element);
    return () => observer.disconnect();
  }, [edit.settings.width, edit.settings.height]);
  const release = useCallback((element: HTMLMediaElement) => {
    element.pause(); const route = routes.current.get(element);
    if (route) for (const node of [route.source, route.gain, route.high, route.high2, route.low, route.equalizer, route.compressor]) node.disconnect();
    routes.current.delete(element);
  }, []);
  const volume = useCallback((element: HTMLMediaElement, value: number, preset: TimelineClip["audio_preset"] = "none") => {
    try {
      const ctx = context.current ||= new AudioContext();
      let route = routes.current.get(element);
      if (!route) { route = { source: ctx.createMediaElementSource(element), gain: ctx.createGain(), high: ctx.createBiquadFilter(), high2: ctx.createBiquadFilter(), low: ctx.createBiquadFilter(), equalizer: ctx.createBiquadFilter(), compressor: ctx.createDynamicsCompressor() }; route.gain.connect(ctx.destination); routes.current.set(element, route); }
      if (route.preset !== preset) {
        for (const node of [route.source, route.high, route.high2, route.low, route.equalizer, route.compressor]) node.disconnect();
        if (preset === "none") route.source.connect(route.gain);
        else {
          const phone = preset === "phone", narration = preset === "narration";
          route.high.type = route.high2.type = "highpass"; route.low.type = "lowpass";
          route.high.frequency.value = route.high2.frequency.value = phone ? 300 : narration ? 65 : 80;
          route.high.Q.value = route.high2.Q.value = route.low.Q.value = Math.SQRT1_2;
          route.low.frequency.value = phone ? 3400 : narration ? 14000 : 12000;
          route.equalizer.type = "peaking"; route.equalizer.frequency.value = 1600; route.equalizer.Q.value = 1; route.equalizer.gain.value = phone ? 2 : 0;
          route.compressor.threshold.value = 20 * Math.log10(phone ? .12 : narration ? .09 : .125);
          route.compressor.knee.value = 0; route.compressor.ratio.value = narration ? 2.2 : 2;
          route.compressor.attack.value = phone ? .008 : narration ? .015 : .01; route.compressor.release.value = phone ? .12 : narration ? .18 : .15;
          route.source.connect(route.high);
          if (phone) { route.high.connect(route.high2); route.high2.connect(route.low); } else route.high.connect(route.low);
          route.low.connect(route.equalizer); route.equalizer.connect(route.compressor); route.compressor.connect(route.gain);
        }
        route.preset = preset;
      }
      route.gain.gain.value = Math.max(0, Math.min(4, value)) * (preset === "phone" ? 1.25 : preset === "none" ? 1 : 1.2); element.volume = 1;
      if (ctx.state === "suspended") void ctx.resume().catch(() => {});
    } catch { element.volume = Math.max(0, Math.min(1, value)); if (value > 1) setError("此浏览器不支持增强音量，导出仍使用设定值。"); }
  }, []);
  useEffect(() => {
    if (!playing) return;
    const origin = performance.now(), start = state.current.time >= duration ? 0 : state.current.time;
    let frame = 0, last = 0;
    const tick = (now: number) => {
      const next = Math.min(duration, start + (now - origin) / 1000);
      if (now - last >= 1000 / edit.settings.fps || next >= duration) { state.current.onTime(next); last = now; }
      if (next >= duration) state.current.onPlayingChange(false);
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration, edit.settings.fps]);
  useEffect(() => () => {
    for (const element of routes.current.keys()) release(element);
    if (context.current) void context.current.close(); context.current = null;
  }, [release]);
  const layers = [...edit.tracks].sort((a, b) => a.order - b.order).filter(track => !track.muted).flatMap(track => edit.clips.filter(clip => !clip.muted && clip.track_id === track.id && time >= clip.start && time < clip.start + clip.duration).map(clip => ({ track, clip })));
  return <div ref={stage} className="timeline-preview" aria-label="多轨实时预览">
    <div className="timeline-preview-stage" style={{ width: edit.settings.width * scale, height: edit.settings.height * scale, backgroundColor: edit.settings.background_color }}>
      <div className="timeline-preview-canvas" style={{ width: edit.settings.width, height: edit.settings.height, transform: `scale(${scale})` }}>
        {layers.map(({ clip, track }) => {
          const local = time - clip.start, type = clip.asset_version_id ? versions[clip.asset_version_id]?.type || versions[clip.asset_version_id]?.mime?.split("/")[0] : "text";
          if (track.type === "audio") return clip.asset_version_id ? <MediaLayer key={clip.id} clip={clip} local={local} playing={playing} kind="audio" setVolume={volume} release={release} onError={setError}/> : null;
          const transform = clip.transform;
          return <div key={clip.id} className={`timeline-preview-layer ${track.type === "text" ? "text" : "visual"}`} style={{ left: transform.x, top: transform.y, width: edit.settings.width - (track.type === "text" ? 80 : 0), ...(track.type !== "text" ? { height: edit.settings.height } : {}), transform: `scale(${transform.scale})`, opacity: transform.opacity * clipGain(clip, local), ...(track.type === "text" ? { fontSize: clip.text_style.font_size, color: clip.text_style.color, backgroundColor: clip.text_style.background_color, textAlign: clip.text_style.align } : {}) }}>
            {track.type === "text" ? clip.text : type === "image" ? <img src={mediaUrl(clip.asset_version_id!, "original")} alt=""/> : clip.asset_version_id ? <MediaLayer clip={clip} local={local} playing={playing} kind="video" setVolume={volume} release={release} onError={setError}/> : null}
          </div>;
        })}
      </div>
    </div>
    {error && <p className="timeline-preview-error" role="status">{error}</p>}
  </div>;
}
