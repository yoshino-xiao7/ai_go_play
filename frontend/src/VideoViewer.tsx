import { useState } from "react";
import { Download } from "lucide-react";
import { mediaUrl } from "./api";
import { Modal } from "./ui";

export default function VideoViewer({ versionId, versions = [], onClose, kind = "video", returnTo }: {
  versionId: string;
  versions?: string[];
  kind?: "video" | "audio";
  onClose: () => void;
  returnTo?: () => HTMLElement | null;
}) {
  const [current, setCurrent] = useState(versionId);
  const [variant, setVariant] = useState("original");
  const [failed, setFailed] = useState(false);
  const [info, setInfo] = useState("");
  const isAudio = kind === "audio";

  const changeVersion = (id: string) => {
    setCurrent(id);
    setVariant("original");
    setFailed(false);
    setInfo("");
  };
  const onError = () => {
    if (variant === "original") setVariant("preview");
    else setFailed(true);
  };
  const source = mediaUrl(current, variant);

  return (
    <div onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}>
      <Modal title={isAudio ? "配音预览" : "视频预览"} onClose={onClose}
        returnTo={returnTo} closeLabel="关闭预览" className="media-viewer-modal" wide>
        <div className="media-player-surface">
          {failed ? <p role="alert">暂时无法播放此版本。可下载原件查看。</p> : isAudio ? (
            <div className="audio-viewer-content">
              <img src={mediaUrl(current, "waveform")} alt="配音波形" />
              <audio key={source} src={source} controls autoPlay preload="metadata" tabIndex={0}
                onLoadedMetadata={event => setInfo(`${event.currentTarget.duration.toFixed(2)} 秒`)} onError={onError} />
            </div>
          ) : (
            <video key={source} src={source} controls autoPlay playsInline preload="metadata" tabIndex={0}
              onLoadedMetadata={event => {
                const { videoWidth, videoHeight, duration } = event.currentTarget;
                setInfo(`${videoWidth} × ${videoHeight} · ${duration.toFixed(2)} 秒`);
              }} onError={onError} />
          )}
        </div>
        <footer className="media-player-footer">
          {versions.length > 1 && <nav aria-label="选择媒体版本">
            {versions.map((id, index) => (
              <button key={id} type="button" className="button secondary" aria-pressed={id === current}
                onClick={() => changeVersion(id)}>版本 {index + 1}</button>
            ))}
          </nav>}
          <span aria-live="polite">{[info, variant === "preview" ? "兼容预览" : ""].filter(Boolean).join(" · ")}</span>
          <a className="button secondary" href={mediaUrl(current, "original", true)} download>
            <Download size={15} />下载原件
          </a>
        </footer>
      </Modal>
    </div>
  );
}
