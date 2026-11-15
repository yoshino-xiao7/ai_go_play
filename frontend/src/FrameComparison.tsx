import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { mediaUrl } from "./api";
import "./frame-comparison.css";

export type FrameComparisonLink = {
  original_node_id: string;
  remake_node_id: string;
  fps: number;
  first_master_frame: number;
  frame_count: number;
};

export type FrameComparisonSources = {
  originalVersionId: string;
  remakeVersionId: string;
  title: string;
  fps: number;
  firstMasterFrame: number;
  frameCount: number;
};

type FrameStatus = { frame: number; state: "ready" | "error" };

function ComparisonVideo({ label, versionId, frame, fps, frameCount, onStatus }: {
  label: string;
  versionId: string;
  frame: number;
  fps: number;
  frameCount: number;
  onStatus: (status: FrameStatus | undefined) => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [variant, setVariant] = useState<"original" | "preview">("original");

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const time = (frame + 0.5) / fps;
    const tolerance = 0.15 / fps;
    let timeout: number | undefined;

    function report(state: FrameStatus["state"]) {
      window.clearTimeout(timeout);
      onStatus({ frame, state });
    }

    function settle() {
      if (!video || video.seeking || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
      if (Math.abs(video.currentTime - time) <= tolerance) report("ready");
    }

    function seek() {
      if (!video || video.readyState < HTMLMediaElement.HAVE_METADATA) return;
      if (!Number.isFinite(video.duration) || Math.abs(video.duration - frameCount / fps) >= 0.75 / fps) {
        report("error");
        return;
      }
      if (Math.abs(video.currentTime - time) > tolerance) video.currentTime = time;
      settle();
    }

    function failed() {
      if (variant === "original") setVariant("preview");
      else report("error");
    }

    onStatus(undefined);
    timeout = window.setTimeout(failed, 8000);
    video.addEventListener("loadedmetadata", seek);
    video.addEventListener("loadeddata", settle);
    video.addEventListener("seeked", settle);
    video.addEventListener("error", failed);
    if (video.error) failed();
    else seek();
    return () => {
      window.clearTimeout(timeout);
      video.removeEventListener("loadedmetadata", seek);
      video.removeEventListener("loadeddata", settle);
      video.removeEventListener("seeked", settle);
      video.removeEventListener("error", failed);
    };
  }, [fps, frame, frameCount, onStatus, variant, versionId]);

  return (
    <figure className="frame-comparison-panel">
      <figcaption>{label}</figcaption>
      <video key={variant} ref={ref} src={mediaUrl(versionId, variant)} aria-label={label} preload="auto" muted playsInline />
    </figure>
  );
}

export default function FrameComparison({ sources, onClose }: {
  sources: FrameComparisonSources | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [frame, setFrame] = useState(0);
  const [original, setOriginal] = useState<FrameStatus>();
  const [remake, setRemake] = useState<FrameStatus>();
  const total = sources?.frameCount || 1;
  const ready = original?.frame === frame && original.state === "ready" && remake?.frame === frame && remake.state === "ready";
  const error = [original?.frame === frame && original.state === "error" ? "原片" : "",
    remake?.frame === frame && remake.state === "error" ? "重制" : ""].filter(Boolean).join("、");

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);

  function step(direction: number) {
    setFrame((current) => Math.max(0, Math.min(total - 1, current + direction)));
  }

  return createPortal(
    <dialog
      className="frame-comparison"
      aria-label="逐帧对照"
      ref={dialogRef}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onKeyDown={(event) => {
        if (!sources || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
        event.preventDefault();
        step(event.key === "ArrowLeft" ? -1 : 1);
      }}
    >
      <header>
        <h2>逐帧对照{sources?.title ? ` · ${sources.title}` : ""}</h2>
        <button type="button" onClick={onClose} aria-label="关闭逐帧对照"><X size={20} /></button>
      </header>
      {sources ? <>
        <div className="frame-comparison-media" data-ready={ready} aria-busy={!ready && !error}>
          <ComparisonVideo label="原片" versionId={sources.originalVersionId} frame={frame} fps={sources.fps} frameCount={total} onStatus={setOriginal} />
          <ComparisonVideo label="重制" versionId={sources.remakeVersionId} frame={frame} fps={sources.fps} frameCount={total} onStatus={setRemake} />
          {!ready && <p className="frame-comparison-status" role={error ? "alert" : "status"}>
            {error ? `${error}无法定位此帧，请检查两张卡片的视频版本和时长。` : "正在定位两段视频的画面…"}
          </p>}
        </div>
        <footer>
          <div className="frame-comparison-control">
            <button type="button" aria-label="上一帧" onClick={() => step(-1)} disabled={frame === 0}><ChevronLeft size={18} /></button>
            <input aria-label="对照帧" type="range" min={0} max={total - 1} value={frame} disabled={total === 1} onChange={(event) => setFrame(event.currentTarget.valueAsNumber)} />
            <button type="button" aria-label="下一帧" onClick={() => step(1)} disabled={frame === total - 1}><ChevronRight size={18} /></button>
          </div>
          <output>镜内帧 F{frame} / F{total - 1} · 全片帧 F{sources.firstMasterFrame + frame} · {sources.fps} fps</output>
        </footer>
      </> : <p role="alert">对照视频或帧范围缺失，请检查原片和重制卡片。</p>}
    </dialog>,
    document.body,
  );
}
