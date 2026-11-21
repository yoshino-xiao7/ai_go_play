import { useEffect, useState } from "react";
import { Palette as PaletteIcon } from "lucide-react";
import {
  currentMotion, currentPalette, onAppearanceChange, setMotion, setPalette,
  type MotionPreference, type Palette,
} from "./design/appearance";
import "./appearance-settings.css";

const palettes: { id: Palette; name: string; note: string }[] = [
  { id: "pale-pink", name: "淡粉亮色", note: "米白纸面、淡粉主色；看片区域保留暗房深色。" },
  { id: "darkroom", name: "暗房深色", note: "原有的深色工作台，适合长时间暗光环境。" },
];
const motions: { id: MotionPreference; name: string; note: string }[] = [
  { id: "system", name: "跟随系统", note: "系统开启“减少动画”时自动减少。" },
  { id: "reduce", name: "减少动效", note: "关闭显影、过渡与呼吸提示，只保留必要状态变化。" },
];

/** Settings → 外观与动效. Choices are stored per browser (localStorage). */
export default function AppearanceSettings() {
  const [palette, setPaletteState] = useState(currentPalette);
  const [motion, setMotionState] = useState(currentMotion);
  useEffect(() => onAppearanceChange(() => { setPaletteState(currentPalette()); setMotionState(currentMotion()); }), []);
  return (
    <section className="settings-card appearance-settings">
      <div className="setting-icon"><PaletteIcon size={24} /></div>
      <div className="setting-body">
        <h2>外观与动效</h2>
        <fieldset className="appearance-choices">
          <legend>配色</legend>
          {palettes.map(item => (
            <label key={item.id} className={`appearance-choice palette-${item.id}`} data-checked={palette === item.id}>
              <input type="radio" name="palette" checked={palette === item.id} onChange={() => setPalette(item.id)} />
              <span className="appearance-swatch" aria-hidden="true"><i /><i /><i /></span>
              <span><strong>{item.name}</strong><small>{item.note}</small></span>
            </label>
          ))}
        </fieldset>
        <fieldset className="appearance-choices">
          <legend>动效</legend>
          {motions.map(item => (
            <label key={item.id} className="appearance-choice" data-checked={motion === item.id}>
              <input type="radio" name="motion" checked={motion === item.id} onChange={() => setMotion(item.id)} />
              <span><strong>{item.name}</strong><small>{item.note}</small></span>
            </label>
          ))}
        </fieldset>
        <p className="muted small">外观只保存在本机浏览器，不影响项目数据与其他设备。</p>
      </div>
    </section>
  );
}
