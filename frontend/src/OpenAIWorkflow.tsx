import { useState } from "react";
import { CheckCircle2, Cloud, LoaderCircle, RefreshCw } from "lucide-react";
import { Modal } from "./ui";
import OpenAIImageControls from "./OpenAIImageControls";
import { useOpenAIImages } from "./openaiImages";
import type { ImageOptions } from "./openaiImages";

export default function OpenAIWorkflow({ onClose }: { onClose: () => void }) {
  const [options, setOptions] = useState<ImageOptions>({ model: "gpt-image-2.6-flare", quality: "high", width: 1024, height: 1024 });
  const config = useOpenAIImages(true, options);
  return <Modal title="OpenAI · 云端图片工作流" onClose={onClose} wide className="openai-workflow-modal">
    <div className="openai-workflow-body">
      <div className="openai-workflow-intro"><Cloud size={28} /><div><h3>文生图、参考生图与图像编辑</h3><p>在画布图片卡的工作流菜单选择 OpenAI，即可使用以下模型与费用预估。此处调整仅用于试算。</p></div></div>
      <div className="openai-connection-state"><CheckCircle2 size={16} />{config.catalogLoading ? "正在检查连接…" : config.catalog?.ready ? `已连接 · ${config.catalog.models.filter(item => item.available).length} 个已接入模型可用` : config.catalog?.configured ? "已配置密钥 · 连接需要检查" : "尚未配置密钥"}</div>
      <OpenAIImageControls options={options} onChange={setOptions} {...config} loading={config.catalogLoading} onRefresh={config.refresh} />
      <section className="openai-model-availability"><h3>已接入的模型</h3>{config.catalog?.models.map(model => <div key={model.id}><span>{model.name}<small>{model.id}</small></span><b className={model.available ? "available" : ""}>{model.available ? "当前项目可用" : "当前不可用"}</b></div>)}</section>
      <p className="openai-cloud-note">连接检查只读取模型列表，不会生成图片。密钥仅由本机后端读取，不会发送给浏览器。模型可见性不代表余额充足，调用仍受项目权限和额度限制。</p>
    </div>
    <footer className="modal-footer"><button className="button secondary" disabled={config.catalogLoading} onClick={config.refresh}>{config.catalogLoading ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}重新检查</button><button className="button primary" onClick={onClose}>完成</button></footer>
  </Modal>;
}
