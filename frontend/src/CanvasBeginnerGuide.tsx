import { useState } from "react";
import { BookOpen, Check, ChevronDown, ChevronUp, Link2, Upload } from "lucide-react";
import "./canvas-beginner-guide.css";

export const beginnerImagePrompt = "雨后的夜晚，一盏暖黄色纸灯笼挂在安静的街角，地面有湿润的倒影，画面干净，电影感光线，横向构图。";
export const beginnerVideoPrompt = "保留参考图的主体和构图，镜头缓慢向前推进，光线和细节轻微变化，动作自然，画面稳定，无突然切换。";

export type BeginnerGuideStep = "image" | "image-result" | "video-node" | "connect" | "video-result" | "done";

const steps = ["创建画布", "准备图片", "连接首帧", "生成视频"];
const instructions: Record<BeginnerGuideStep, { index: number; title: string; detail: string }> = {
  image: { index: 1, title: "准备一张图片", detail: "可以新建文生图节点，或导入一张本机图片作为视频首帧。" },
  "image-result": { index: 1, title: "生成你的第一张图", detail: "示例提示词已填好，可以修改。选择可用的生图工作流，再点图片面板里的「生成图片」。如果出现候选，选一张采用。" },
  "video-node": { index: 2, title: "创建视频节点", detail: "用刚才的图片做开场画面。视频节点会预填一段运镜提示词，并使用首尾帧模式。" },
  connect: { index: 2, title: "把图片连到视频", detail: "从图片右侧的圆点拖到视频左侧的圆点，让图片成为首帧。也可以点击下方按钮完成连线。" },
  "video-result": { index: 3, title: "让画面动起来", detail: "检查视频面板里的首帧和提示词，由你点击「生成视频」。结果回来后可以直接在卡片上播放。" },
  done: { index: 3, title: "第一个镜头完成", detail: "图片、连线和视频都在这张练习画布里，可以继续编辑。想再练一次，可回项目页重新打开新手引导。" },
};

type Props = {
  step: BeginnerGuideStep;
  busy: boolean;
  onImage: () => void;
  onImport: () => void;
  onVideo: () => void;
  onConnect: () => void;
  onLocate: () => void;
  onSetup: () => void;
  onClose: () => void;
};

export default function CanvasBeginnerGuide(props: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const { step, busy } = props;
  const { index, title, detail } = instructions[step];
  const canImport = step === "image" || step === "image-result";
  return (
    <aside className="canvas-beginner-guide" aria-label="新手引导">
      <div className="canvas-guide-heading">
        <strong><BookOpen size={16} /> 新手引导</strong>
        <button className="canvas-icon-button" title={collapsed ? "展开引导" : "收起引导"}
          aria-label={collapsed ? "展开引导" : "收起引导"} aria-expanded={!collapsed}
          onClick={() => setCollapsed(value => !value)}>
          {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
      </div>
      {!collapsed && <>
        <ol className="canvas-guide-steps" aria-label="引导进度">
          {steps.map((label, i) => <li key={label} aria-current={i === index && step !== "done" ? "step" : undefined}
            className={i < index || step === "done" ? "is-done" : i === index ? "is-current" : ""}>
            <span>{i < index || step === "done" ? <Check size={12} aria-label="已完成" /> : i + 1}</span>{label}
          </li>)}
        </ol>
        <div className="canvas-guide-instruction" aria-live="polite">
          <h2>{title}</h2>
          <p>{detail}</p>
        </div>
        <div className="canvas-guide-actions">
          {step === "image" && <button className="canvas-small-button canvas-guide-primary" disabled={busy} onClick={props.onImage}>创建图片节点</button>}
          {canImport && <button className="canvas-small-button" disabled={busy} onClick={props.onImport}><Upload size={14} />导入本机图片</button>}
          {step === "video-node" && <button className="canvas-small-button canvas-guide-primary" disabled={busy} onClick={props.onVideo}>创建视频节点</button>}
          {step === "connect" && <button className="canvas-small-button canvas-guide-primary" onClick={props.onConnect}><Link2 size={14} />连接为首帧</button>}
          {(step === "image-result" || step === "video-result") && <button className="canvas-small-button" onClick={props.onLocate}>定位创作节点</button>}
          {step === "done" && <button className="canvas-small-button canvas-guide-primary" onClick={props.onClose}>完成引导</button>}
        </div>
        {step !== "done" && <div className="canvas-guide-footer">
          <button onClick={props.onSetup}>检查模型配置</button>
          <button onClick={props.onClose}>跳过引导</button>
        </div>}
      </>}
    </aside>
  );
}
