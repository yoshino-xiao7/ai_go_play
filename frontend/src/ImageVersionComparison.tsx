import { useState } from "react";
import type { CSSProperties } from "react";
import { mediaUrl } from "./api";
import "./image-version-comparison.css";

export default function ImageVersionComparison({
  previous,
  variant,
  revision,
}: {
  previous: string;
  variant: "original" | "thumbnail";
  revision: number;
}) {
  const [position, setPosition] = useState(50);
  const [loaded, setLoaded] = useState(false);

  return (
    <div
      className={`image-version-comparison${loaded ? " is-ready" : ""}`}
      style={{ "--comparison-position": `${position}%` } as CSSProperties}
      onPointerMove={(event) => {
        if (event.pointerType !== "mouse" || event.buttons || !loaded ||
            (event.target instanceof Element && event.target.closest(".image-comparison-control"))) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (bounds.width > 0) {
          setPosition(Math.max(0, Math.min(100, Math.round((event.clientX - bounds.left) / bounds.width * 100))));
        }
      }}
    >
      <div className="image-comparison-before" aria-hidden="true">
        <img
          src={`${mediaUrl(previous, variant)}&refresh=${revision}`}
          alt=""
          draggable={false}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setLoaded(false)}
        />
      </div>
      {loaded && <>
        <div className="image-comparison-line" aria-hidden="true" />
        <div className="image-comparison-labels" aria-hidden="true">
          <span>上一版</span><span>当前版</span>
        </div>
        <label
          className="image-comparison-control nodrag nopan"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <span>对比上一版</span>
          <input
            type="range"
            min={0}
            max={100}
            value={position}
            aria-label="新旧图片分割位置"
            onChange={(event) => setPosition(event.currentTarget.valueAsNumber)}
          />
        </label>
      </>}
    </div>
  );
}
