import { useEffect, useRef } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ArrowUpRight, Crosshair, Focus, MoveDiagonal, RotateCw, Scan, Video, Waves, X } from "lucide-react";
import StudioSelect from "./StudioSelect";

export const cameraPresets = {
  static: { label: "固定机位", Icon: Scan },
  follow_front: { label: "迎面跟拍", Icon: Crosshair },
  follow_side: { label: "侧面跟拍", Icon: Video },
  truck_left: { label: "镜头左移", Icon: ArrowLeft },
  truck_right: { label: "镜头右移", Icon: ArrowRight },
  pedestal_up: { label: "镜头上移", Icon: ArrowUp },
  pedestal_down: { label: "镜头下移", Icon: ArrowDown },
  dolly_in: { label: "推进", Icon: MoveDiagonal },
  dolly_out: { label: "后拉", Icon: ArrowUpRight },
  orbit: { label: "环绕", Icon: RotateCw },
  handheld: { label: "手持拍摄", Icon: Waves },
  rack_focus: { label: "焦点转移", Icon: Focus },
};

type Preset = keyof typeof cameraPresets;
export type CameraMotion = {
  preset: Preset;
  amplitude: "small" | "medium" | "large";
  speed: "slow" | "normal" | "fast";
};

const presets = Object.entries(cameraPresets) as [Preset, (typeof cameraPresets)[Preset]][];
const amplitudes = { small: "小", medium: "中", large: "大" };
const speeds = { slow: "慢", normal: "正常", fast: "快" };
const hasTuning = (preset: Preset) => preset !== "static" && preset !== "rack_focus";

export function cameraMotionLabel(motion: CameraMotion) {
  const label = cameraPresets[motion.preset].label;
  return hasTuning(motion.preset) ? `${label} · ${amplitudes[motion.amplitude]}幅度 · ${speeds[motion.speed]}` : label;
}

export function CameraMotionPicker({ onChoose, onClose }: {
  onChoose: (motion: CameraMotion) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return (
    <dialog ref={dialog} className="camera-motion-picker" aria-modal="true" aria-labelledby="camera-motion-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <section>
        <header>
          <div><small>导演工具箱</small><h2 id="camera-motion-title">运镜</h2></div>
          <button type="button" className="icon-button" aria-label="关闭运镜预设" onClick={onClose}><X size={18} /></button>
        </header>
        <p>选择一种镜头运动，再将卡片连到 H3 视频节点。示意图用于辨认运镜方向。</p>
        <div className="camera-motion-grid">
          {presets.map(([preset, { label, Icon }]) => (
            <button type="button" key={preset} onClick={() => onChoose({ preset, amplitude: "medium", speed: "normal" })}>
              <span className="camera-motion-diagram"><Icon size={25} strokeWidth={1.5} /></span>
              <span>{label}</span>
            </button>
          ))}
        </div>
      </section>
    </dialog>
  );
}

export function CameraMotionFields({ value, locked, onChange }: {
  value: CameraMotion;
  locked?: boolean;
  onChange: (value: CameraMotion) => void;
}) {
  const { Icon } = cameraPresets[value.preset];
  return (
    <div className="camera-motion-fields nodrag nopan nowheel" onPointerDown={event => event.stopPropagation()}>
      <div className="camera-motion-type">
        <Icon size={20} strokeWidth={1.5} />
        <StudioSelect aria-label="运镜预设" value={value.preset} disabled={locked}
          onChange={event => onChange({ ...value, preset: event.target.value as Preset })}>
          {presets.map(([id, preset]) => <option key={id} value={id}>{preset.label}</option>)}
        </StudioSelect>
      </div>
      {hasTuning(value.preset) && <div className="camera-motion-tuning">
        <label>幅度<StudioSelect aria-label="运镜幅度" value={value.amplitude} disabled={locked}
          onChange={event => onChange({ ...value, amplitude: event.target.value as CameraMotion["amplitude"] })}>
          {Object.entries(amplitudes).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </StudioSelect></label>
        <label>速度<StudioSelect aria-label="运镜速度" value={value.speed} disabled={locked}
          onChange={event => onChange({ ...value, speed: event.target.value as CameraMotion["speed"] })}>
          {Object.entries(speeds).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </StudioSelect></label>
      </div>}
      <small>连接到 H3 视频 · 提示词控制</small>
    </div>
  );
}
