import { memo } from "react";
import { BaseEdge, getBezierPath } from "@xyflow/react";
import type { EdgeProps } from "@xyflow/react";

/** Stable 0..1 phase per edge so sparks along different wires never march in lockstep. */
function phase(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return ((h >>> 0) % 1000) / 1000;
}

// A wire: a quiet stroke that takes the accent on hover/selection, a soft glow underlay, the
// active-connection flow marks, and a spark that travels selected wires (colours live in nodes.css).
export default memo(function CanvasConnectionEdge({
  id, sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  label, labelStyle, labelShowBg, labelBgStyle, labelBgPadding, labelBgBorderRadius,
  style, interactionWidth,
}: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });
  const begin = `${(-phase(id) * 2.8).toFixed(2)}s`;
  return <>
    <path className="canvas-edge-glow" d={path} fill="none" aria-hidden="true" />
    <BaseEdge id={id} path={path} labelX={labelX} labelY={labelY} label={label}
      labelStyle={labelStyle} labelShowBg={labelShowBg} labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding} labelBgBorderRadius={labelBgBorderRadius}
      style={style} interactionWidth={interactionWidth} />
    <path className="canvas-edge-tail" d={path} pathLength={100} fill="none" aria-hidden="true" />
    <path className="canvas-edge-flow" d={path} pathLength={100} fill="none" aria-hidden="true" />
    <circle className="canvas-edge-spark" r="2.5" aria-hidden="true">
      <animateMotion dur="2.8s" begin={begin} repeatCount="indefinite" path={path} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.45 0 0.55 1" />
    </circle>
  </>;
});
