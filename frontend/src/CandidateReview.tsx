import { useEffect, useRef } from "react";
import { mediaUrl } from "./api";
import type { ImageHistoryItem } from "./generationTypes";

export type ImageReview = {
  adopted?: string;
  history: ImageHistoryItem[];
  locked?: boolean;
  onAdopt: (id: string) => void;
  onContinue: (id: string) => void;
  onDiscard: (id: string) => void;
};

export default function CandidateReview({
  review,
  selected,
  comparing,
  onSelect,
  onCompare,
}: {
  review: ImageReview;
  selected: string;
  comparing: boolean;
  onSelect: (id: string) => void;
  onCompare: () => void;
}) {
  const tray = useRef<HTMLDivElement>(null);
  const active = useRef<HTMLButtonElement>(null);
  const { adopted, history, locked, onAdopt, onContinue, onDiscard } = review;
  const isAdopted = selected === adopted;
  const isCandidate = history.find((item) => item.version_id === selected)?.candidate;

  useEffect(() => {
    active.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selected]);

  useEffect(() => {
    const element = tray.current;
    if (!element) return;
    const scroll = (event: WheelEvent) => {
      if (event.ctrlKey || event.shiftKey || Math.abs(event.deltaX) >= Math.abs(event.deltaY) ||
          element.scrollWidth <= element.clientWidth) return;
      event.preventDefault();
      const factor = event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 16 :
        event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? element.clientWidth : 1;
      element.scrollLeft += event.deltaY * factor;
    };
    element.addEventListener("wheel", scroll, { passive: false });
    return () => element.removeEventListener("wheel", scroll);
  }, []);

  return (
    <section className="candidate-review" aria-label="图片版本">
      <div className="candidate-thumbnails" ref={tray} aria-label="版本缩略图">
        {history.map((item, index) => {
          const isActive = item.version_id === selected;
          const status = item.version_id === adopted ? "已采用" : item.candidate ? "候选" : "历史";
          return (
            <button
              key={item.version_id}
              ref={isActive ? active : undefined}
              type="button"
              aria-label={`预览版本 ${index + 1} · ${status}`}
              aria-pressed={isActive}
              onClick={() => onSelect(item.version_id)}
            >
              <img src={mediaUrl(item.version_id, "thumbnail")} alt="" loading="lazy" draggable={false} />
              <span><b>{index + 1}</b>{status}</span>
            </button>
          );
        })}
      </div>
      <div className="candidate-actions">
        <button type="button" disabled={!adopted || isAdopted} aria-pressed={comparing} onClick={onCompare}>
          {comparing ? "结束对比" : "与已采用对比"}
        </button>
        <button type="button" disabled={locked} onClick={() => onContinue(selected)}>从此版本修改</button>
        {isCandidate && !isAdopted && (
          <button type="button" disabled={locked} onClick={() => onDiscard(selected)}>移出候选</button>
        )}
        <button type="button" className="candidate-adopt" disabled={locked || isAdopted} onClick={() => onAdopt(selected)}>
          {isAdopted ? "当前已采用" : "采用此版本"}
        </button>
      </div>
    </section>
  );
}
