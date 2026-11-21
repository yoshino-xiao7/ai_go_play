import StudioSelect from "./StudioSelect";
import { AlertCircle, Cloud, ExternalLink, LoaderCircle, RefreshCw } from "lucide-react";
import type { ImageEstimate, ImageOptions, OpenAIImageCatalog } from "./openaiImages";

type Props = {
  options: ImageOptions;
  catalog?: OpenAIImageCatalog;
  estimate?: ImageEstimate;
  issue?: string;
  loading?: boolean;
  disabled?: boolean;
  referenceCount?: number;
  onChange: (options: ImageOptions) => void;
  onRefresh: () => void;
};

export default function OpenAIImageControls({ options, catalog, estimate, issue, loading, disabled, referenceCount = 0, onChange, onRefresh }: Props) {
  const selected = catalog?.models.find(item => item.id === options.model);
  const sizeValue = `${options.width}x${options.height}`;
  const preset = catalog?.sizes.some(item => `${item.width}x${item.height}` === sizeValue);
  const patch = (changes: Partial<ImageOptions>) => onChange({ ...options, ...changes });
  return <section className="openai-image-controls" aria-label="OpenAI 图片设置">
    <header><strong><Cloud size={14} />OpenAI 云端图片</strong><a href="#/workflows">管理工作流</a><button type="button" aria-label="重新检查 OpenAI 模型" disabled={loading} onClick={onRefresh}>{loading ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}</button></header>
    <div className="openai-options-grid">
      <label className="openai-model-field">模型<StudioSelect aria-label="OpenAI 图片模型" value={options.model} disabled={disabled || loading} onChange={event => {
        const next = catalog?.models.find(item => item.id === event.target.value);
        patch({ model: event.target.value, quality: next?.qualities.includes(options.quality) ? options.quality : "high" });
      }}>
        {!selected && <option value={options.model}>{options.model}</option>}
        {catalog?.models.map(item => <option value={item.id} key={item.id} disabled={!item.available}>{item.name}{item.available ? "" : " · 当前不可用"}</option>)}
      </StudioSelect></label>
      <label>画质<StudioSelect aria-label="OpenAI 图片画质" value={options.quality} disabled={disabled} onChange={event => patch({ quality: event.target.value })}>
        {(selected?.qualities || ["low", "medium", "high", "xhigh", "max"]).map(value => <option key={value} value={value}>{catalog?.quality_names[value] || value} · {value}</option>)}
      </StudioSelect></label>
      <label>输出尺寸<StudioSelect aria-label="OpenAI 图片尺寸" value={preset ? sizeValue : "custom"} disabled={disabled} onChange={event => {
        if (event.target.value === "custom") return;
        const [width, height] = event.target.value.split("x").map(Number);
        patch({ width, height });
      }}>
        {!preset && <option value="custom">自定义 · {sizeValue}</option>}
        {catalog?.sizes.map(item => <option key={item.label} value={`${item.width}x${item.height}`}>{item.label}</option>)}
      </StudioSelect></label>
    </div>
    <details className="openai-custom-dimensions"><summary>自定义尺寸</summary><div>
      <label>宽度<input aria-label="OpenAI 自定义宽度" type="number" min={16} max={3840} step={16} value={options.width} disabled={disabled} onChange={event => patch({ width: Number(event.target.value) })} /></label>
      <label>高度<input aria-label="OpenAI 自定义高度" type="number" min={16} max={3840} step={16} value={options.height} disabled={disabled} onChange={event => patch({ height: Number(event.target.value) })} /></label>
    </div><p>宽高为 16 的倍数，长边 ≤ 3840，比例 ≤ 3:1，总像素 655360–8294400。</p></details>
    <div className="openai-cost-estimate" role="status" aria-live="polite">
      <div><span>单张图片输出预估</span><strong>{estimate ? `$${estimate.output_usd.toFixed(5)}` : "—"}</strong></div>
      <p>提示词{referenceCount ? `及 ${referenceCount} 张参考图` : "与参考图"}输入另计，最终以实际用量为准。</p>
      {estimate && <a href={estimate.pricing_url} target="_blank" rel="noreferrer">价格基准 {estimate.pricing_date}<ExternalLink size={11} /></a>}
    </div>
    {issue && <p className="openai-config-issue" role="alert"><AlertCircle size={13} />{issue}</p>}
    <p className="openai-cloud-note">提交将向 OpenAI 发送描述和所选参考图。每次生成 1 张，结果保存到本地资产库。</p>
  </section>;
}
