import { useEffect, useRef, useState } from "react";
import { Brush, Eraser, LoaderCircle, Trash2, Undo2 } from "lucide-react";
import { mediaUrl, uploadAsset } from "./api";
import { Modal } from "./ui";
import "./generation.css";

type Stroke = {
  points: { x: number; y: number }[];
  size: number;
  erase: boolean;
};

export default function MaskEditor({
  projectId,
  versionId,
  onSave,
  onClose,
}: {
  projectId: string;
  versionId: string;
  onSave: (versionId: string) => void;
  onClose: () => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const strokes = useRef<Stroke[]>([]);
  const drawing = useRef(false);
  const [size, setSize] = useState(64);
  const [erase, setErase] = useState(false);
  const [dimensions, setDimensions] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [revision, setRevision] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const paintStroke = (context: CanvasRenderingContext2D, stroke: Stroke) => {
    context.globalCompositeOperation = stroke.erase
      ? "destination-out"
      : "source-over";
    context.strokeStyle = "white";
    context.fillStyle = "white";
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineWidth = stroke.size;
    context.beginPath();
    const first = stroke.points[0];
    if (!first) return;
    context.moveTo(first.x, first.y);
    if (stroke.points.length === 1) {
      context.arc(first.x, first.y, stroke.size / 2, 0, Math.PI * 2);
      context.fill();
    } else {
      stroke.points
        .slice(1)
        .forEach((point) => context.lineTo(point.x, point.y));
      context.stroke();
    }
  };

  useEffect(() => {
    if (!canvas.current || !dimensions) return;
    canvas.current.width = dimensions.width;
    canvas.current.height = dimensions.height;
    const context = canvas.current.getContext("2d");
    if (!context) return;
    for (const stroke of strokes.current) paintStroke(context, stroke);
  }, [dimensions, revision]);

  const pointFromEvent = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x:
        ((event.clientX - bounds.left) / bounds.width) *
        event.currentTarget.width,
      y:
        ((event.clientY - bounds.top) / bounds.height) *
        event.currentTarget.height,
    };
  };

  const save = async () => {
    if (!canvas.current || !dimensions || !strokes.current.length) return;
    setSaving(true);
    setError("");
    try {
      const output = document.createElement("canvas");
      output.width = dimensions.width;
      output.height = dimensions.height;
      const context = output.getContext("2d");
      if (!context) throw new Error("浏览器无法创建蒙版。");
      context.fillStyle = "black";
      context.fillRect(0, 0, output.width, output.height);
      context.drawImage(canvas.current, 0, 0);
      const pixels = context.getImageData(
        0,
        0,
        output.width,
        output.height,
      ).data;
      let covered = 0;
      for (let index = 0; index < pixels.length; index += 4)
        covered += pixels[index] / 255;
      if (covered / (output.width * output.height) <= 0.002)
        throw new Error("涂抹区域过小，请扩大需要修改的区域后再保存。");
      const blob = await new Promise<Blob>((resolve, reject) =>
        output.toBlob(
          (value) =>
            value ? resolve(value) : reject(new Error("蒙版导出失败。")),
          "image/png",
        ),
      );
      const asset = await uploadAsset(
        new File([blob], `局部编辑蒙版-${Date.now()}.png`, {
          type: "image/png",
        }),
        { projectId },
      );
      onSave(asset.imported_version_id || asset.current_version_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="绘制局部编辑蒙版"
      wide
      onClose={() => {
        if (!saving) onClose();
      }}
    >
      <div className="mask-editor">
        <div className="mask-editor-stage">
          <div
            className="mask-image-stack"
            style={{
              width: dimensions
                ? `min(100%, ${(dimensions.width / dimensions.height) * 440}px)`
                : "100%",
              aspectRatio: dimensions
                ? `${dimensions.width}/${dimensions.height}`
                : "1",
            }}
          >
            <img
              src={mediaUrl(versionId, "original")}
              alt="编辑底图"
              draggable={false}
              onLoad={(event) =>
                setDimensions({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                })
              }
              onError={() => setError("底图无法加载，请先修复资产文件。")}
            />
            <canvas
              ref={canvas}
              aria-label="蒙版画布"
              className="mask-brush-canvas"
              onPointerDown={(event) => {
                if (!dimensions || saving || event.button !== 0) return;
                event.currentTarget.setPointerCapture(event.pointerId);
                drawing.current = true;
                const stroke = { points: [pointFromEvent(event)], size, erase };
                strokes.current.push(stroke);
                const context = event.currentTarget.getContext("2d");
                if (context) paintStroke(context, stroke);
              }}
              onPointerMove={(event) => {
                if (!drawing.current) return;
                const stroke = strokes.current[strokes.current.length - 1];
                const previous = stroke.points[stroke.points.length - 1];
                const point = pointFromEvent(event);
                stroke.points.push(point);
                const context = event.currentTarget.getContext("2d");
                if (context)
                  paintStroke(context, {
                    ...stroke,
                    points: [previous, point],
                  });
              }}
              onPointerUp={(event) => {
                drawing.current = false;
                if (event.currentTarget.hasPointerCapture(event.pointerId))
                  event.currentTarget.releasePointerCapture(event.pointerId);
                setRevision((value) => value + 1);
              }}
              onPointerCancel={() => {
                drawing.current = false;
                setRevision((value) => value + 1);
              }}
            />
          </div>
        </div>
        <aside className="mask-editor-tools">
          <h3>涂抹需要修改的区域</h3>
          <p>涂抹需要改变的部分，未涂抹区域尽量保留，边缘会平滑过渡。</p>
          <div className="mask-tool-buttons">
            <button
              className={!erase ? "active" : ""}
              onClick={() => setErase(false)}
            >
              <Brush size={15} />
              画笔
            </button>
            <button
              className={erase ? "active" : ""}
              onClick={() => setErase(true)}
            >
              <Eraser size={15} />
              橡皮
            </button>
          </div>
          <label>
            画笔大小 <span>{size} px</span>
            <input
              type="range"
              min={8}
              max={256}
              step={4}
              value={size}
              onChange={(event) => setSize(Number(event.target.value))}
            />
          </label>
          <button
            className="mask-secondary"
            onClick={() => {
              strokes.current.pop();
              setRevision((value) => value + 1);
            }}
            disabled={!strokes.current.length || saving}
          >
            <Undo2 size={14} />
            撤销一笔
          </button>
          <button
            className="mask-secondary"
            onClick={() => {
              strokes.current = [];
              setRevision((value) => value + 1);
            }}
            disabled={!strokes.current.length || saving}
          >
            <Trash2 size={14} />
            清空蒙版
          </button>
          {dimensions && (
            <span className="mask-dimensions">
              {dimensions.width} × {dimensions.height}
            </span>
          )}
          {error && (
            <p className="generation-error" role="alert">
              {error}
            </p>
          )}
        </aside>
      </div>
      <footer className="modal-footer">
        <button
          className="button secondary"
          onClick={onClose}
          disabled={saving}
        >
          取消
        </button>
        <button
          className="button primary"
          onClick={() => void save()}
          disabled={!dimensions || !strokes.current.length || saving}
        >
          {saving ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Brush size={15} />
          )}
          {saving ? "保存蒙版中" : "使用此蒙版"}
        </button>
      </footer>
    </Modal>
  );
}
