import type { ReactNode, RefObject } from "react";
import { useStore } from "@xyflow/react";

type Props = {
  anchor: { x: number; y: number; width: number; height: number };
  expanded: boolean;
  inset: { left: number; right: number };
  panelRef: RefObject<HTMLElement | null>;
  toolbar: ReactNode;
  children: ReactNode;
};

const gap = 8;
const barHeight = 38;
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max));

export default function CanvasCardControls({ anchor, expanded, inset, panelRef, toolbar, children }: Props) {
  const [tx, ty, zoom] = useStore(state => state.transform);
  const stageWidth = useStore(state => state.width);
  const stageHeight = useStore(state => state.height);
  const left = anchor.x * zoom + tx;
  const top = anchor.y * zoom + ty;
  const right = left + anchor.width * zoom;
  const bottom = top + anchor.height * zoom;
  const leftBound = inset.left;
  const rightBound = Math.max(leftBound + 1, stageWidth - inset.right);
  const topBound = 14;
  const bottomBound = Math.max(topBound + 1, stageHeight - 58);
  const usableWidth = rightBound - leftBound;
  const usableHeight = bottomBound - topBound;
  const above = top - gap - barHeight >= topBound;
  const barWidth = Math.min(210, usableWidth);
  const barX = clamp(left, leftBound, rightBound - barWidth);
  const barY = clamp(above ? top - gap - barHeight : bottom + gap, topBound, bottomBound - barHeight);

  let editorWidth = Math.min(640, usableWidth);
  let editorHeight = Math.min(460, usableHeight);
  let editorX = clamp(left, leftBound, rightBound - editorWidth);
  let editorY = clamp(top, topBound, bottomBound - editorHeight);
  const rightStart = Math.max(leftBound, right + gap);
  const leftEnd = Math.min(rightBound, left - gap);
  const rightRoom = rightBound - rightStart;
  const leftRoom = leftEnd - leftBound;
  const sideRoom = Math.max(rightRoom, leftRoom);
  const upperEnd = Math.min(bottomBound, (above ? barY : top) - gap);
  const lowerStart = Math.max(topBound, (above ? bottom : barY + barHeight) + gap);
  const upperRoom = upperEnd - topBound;
  const lowerRoom = bottomBound - lowerStart;
  const useLower = lowerRoom >= 325 || lowerRoom >= upperRoom;
  const verticalRoom = useLower ? lowerRoom : upperRoom;
  let editorAbove = false;

  if (verticalRoom < 325 && sideRoom >= Math.min(485, editorWidth)) {
    editorWidth = Math.min(editorWidth, sideRoom);
    editorX = rightRoom >= editorWidth ? rightStart : leftEnd - editorWidth;
  } else {
    editorHeight = Math.min(editorHeight, Math.max(160, verticalRoom));
    editorY = useLower ? clamp(lowerStart, topBound, bottomBound - editorHeight) : Math.max(topBound + editorHeight, upperEnd);
    editorAbove = !useLower;
  }
  const visible = stageWidth > 0 && usableWidth >= 80 && right > leftBound && left < rightBound && bottom > 0 && top < stageHeight;

  return (
    <section ref={panelRef} className="canvas-card-controls nodrag nopan nowheel" aria-label="卡片操作"
      style={{ visibility: visible ? "visible" : "hidden" }}
      onPointerDown={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}>
      <div className="card-control-bar" role="group" aria-label="选中卡片快捷操作"
        style={{ left: barX, top: barY, maxWidth: barWidth }}>
        {toolbar}
      </div>
      <div className="card-control-editor" hidden={!expanded}
        style={{ left: editorX, top: editorY, width: editorWidth, maxHeight: editorHeight,
          transform: editorAbove ? "translateY(-100%)" : undefined }}>
        {children}
      </div>
    </section>
  );
}
