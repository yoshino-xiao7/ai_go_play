import { memo } from "react";
import { BaseEdge, getBezierPath } from "@xyflow/react";
import type { EdgeProps } from "@xyflow/react";

export default memo(function CanvasConnectionEdge({
  id, sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  label, labelStyle, labelShowBg, labelBgStyle, labelBgPadding, labelBgBorderRadius,
  style, interactionWidth,
}: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });
  return <>
    <BaseEdge id={id} path={path} labelX={labelX} labelY={labelY} label={label}
      labelStyle={labelStyle} labelShowBg={labelShowBg} labelBgStyle={labelBgStyle}
      labelBgPadding={labelBgPadding} labelBgBorderRadius={labelBgBorderRadius}
      style={style} interactionWidth={interactionWidth} />
    <path className="canvas-edge-tail" d={path} pathLength={100} fill="none" aria-hidden="true" />
    <path className="canvas-edge-flow" d={path} pathLength={100} fill="none" aria-hidden="true" />
  </>;
});
