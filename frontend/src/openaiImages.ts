import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

export type OpenAIImageCatalog = {
  provider: "openai";
  configured: boolean;
  ready: boolean;
  models: { id: string; name: string; qualities: string[]; available: boolean }[];
  sizes: { label: string; width: number; height: number }[];
  quality_names: Record<string, string>;
  checked_at: string | null;
  error: string;
  pricing_date: string;
  pricing_url: string;
};
export type ImageOptions = { model: string; quality: string; width: number; height: number };
export type ImageEstimate = {
  currency: "USD";
  output_tokens: number;
  output_usd: number;
  pricing_date: string;
  pricing_url: string;
  note: string;
};

export function useOpenAIImages(enabled: boolean, options: ImageOptions) {
  const [catalog, setCatalog] = useState<OpenAIImageCatalog>();
  const [catalogError, setCatalogError] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [quote, setQuote] = useState<{ key: string; value?: ImageEstimate; error?: string }>();
  const key = JSON.stringify(options);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const controller = new AbortController();
    setCatalogLoading(true);
    setCatalogError("");
    api<OpenAIImageCatalog>(`/api/openai/images${revision ? "?refresh=true" : ""}`, { signal: controller.signal })
      .then(value => { if (alive) setCatalog(value); })
      .catch(error => { if (alive) { setCatalog(undefined); setCatalogError(error.message); } })
      .finally(() => { if (alive) setCatalogLoading(false); });
    return () => { alive = false; controller.abort(); };
  }, [enabled, revision]);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api<ImageEstimate>("/api/openai/images/estimate", {
        method: "POST", signal: controller.signal,
        body: JSON.stringify({ model: options.model, quality: options.quality, parameters: { width: options.width, height: options.height } }),
      }).then(value => { if (!controller.signal.aborted) setQuote({ key, value }); })
        .catch(error => { if (!controller.signal.aborted) setQuote({ key, error: error.message }); });
    }, 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [enabled, key]);
  const estimate = quote?.key === key ? quote.value : undefined;
  const estimateError = quote?.key === key ? quote.error || "" : "";
  const model = catalog?.models.find(item => item.id === options.model);
  const issue = !enabled ? "" : catalogLoading ? "正在检查 OpenAI 模型…" : catalogError || catalog?.error ||
    (!catalog?.ready ? "当前项目没有可用的已接入图片模型。" : !model?.available ? "请选择当前项目可用的图片模型。" :
      !model.qualities.includes(options.quality) ? "当前模型不支持所选画质。" : estimateError || (!estimate ? "正在计算费用预估…" : ""));
  return { catalog, catalogLoading, catalogError, estimate, estimateError, issue, refresh };
}
