import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Columns2, Maximize2, Pause, Play, Volume2, VolumeX } from "lucide-react";
import { mediaUrl } from "./api";

function timeLabel(seconds: number) {
  const whole = Math.floor(seconds);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

export default function CanvasVideoPlayer({ versionId, selected, previewOpen, onOpen, onCompare }: {
  versionId: string;
  selected: boolean;
  previewOpen: boolean;
  onOpen: () => void;
  onCompare?: () => void;
}) {
  const player = useRef<HTMLVideoElement>(null);
  const wantsPlayback = useRef(false);
  const [variant, setVariant] = useState<"original" | "preview">("original");
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!selected || previewOpen) {
      wantsPlayback.current = false;
      player.current?.pause();
    }
  }, [selected, previewOpen]);

  const togglePlayback = () => {
    const video = player.current;
    if (!video) return;
    if (video.paused) {
      wantsPlayback.current = true;
      void video.play().catch(() => { /* The media error handler switches to the compatible source. */ });
    } else {
      wantsPlayback.current = false;
      video.pause();
    }
  };

  return <>
    <video
      ref={player}
      className="inline-video"
      src={mediaUrl(versionId, variant)}
      poster={mediaUrl(versionId)}
      playsInline
      muted={muted}
      preload={selected ? "metadata" : "none"}
      autoPlay={variant === "preview" && wantsPlayback.current}
      onDurationChange={({ currentTarget }) => setDuration(Number.isFinite(currentTarget.duration) ? currentTarget.duration : 0)}
      onTimeUpdate={({ currentTarget }) => setTime(currentTarget.currentTime)}
      onPlay={() => setPlaying(true)}
      onPause={() => setPlaying(false)}
      onEnded={() => { wantsPlayback.current = false; setPlaying(false); }}
      onError={() => {
        setPlaying(false);
        if (variant === "original") setVariant("preview");
        else setFailed(true);
      }}
    />
    {failed && <span className="canvas-video-error" role="status">视频暂不可播放</span>}
    <div
      className="canvas-video-controls nodrag nopan nowheel"
      role="group"
      aria-label="视频播放控件"
      onPointerDown={event => event.stopPropagation()}
      onClick={event => event.stopPropagation()}
      onDoubleClick={event => event.stopPropagation()}
      onKeyDown={event => event.stopPropagation()}
    >
      <div className="canvas-video-transport">
        <button type="button" aria-label={playing ? "暂停视频" : "播放视频"} disabled={failed} onClick={togglePlayback}>
          {playing ? <Pause size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" />}
        </button>
        <span className="canvas-video-time">
          {timeLabel(time)} <span>/ {duration ? timeLabel(duration) : "--:--"}</span>
        </span>
      </div>
      <div className="canvas-video-actions">
        <button type="button" aria-label={muted ? "取消静音" : "静音"} onClick={() => setMuted(value => !value)}>
          {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
        </button>
        {onCompare && <button type="button" aria-label="逐帧对照" title="逐帧对照" onClick={() => { player.current?.pause(); onCompare(); }}><Columns2 size={14} /></button>}
        <button type="button" aria-label="查看完整视频" onClick={onOpen}><Maximize2 size={14} /></button>
      </div>
      <input
        type="range"
        aria-label="视频播放进度"
        aria-valuetext={timeLabel(time)}
        min={0}
        max={duration || 1}
        step="any"
        value={time}
        disabled={!duration || failed}
        style={{ "--video-progress": `${duration ? Math.min(100, time / duration * 100) : 0}%` } as CSSProperties}
        onChange={event => {
          const next = event.currentTarget.valueAsNumber;
          if (player.current) player.current.currentTime = next;
          setTime(next);
        }}
      />
    </div>
  </>;
}
