import type { Step } from "./types";
export const steps: { id: Step; name: string; description: string }[] = [
  { id: "welcome", name: "开始准备", description: "了解你的本地创作空间" },
  { id: "comfy", name: "生成引擎", description: "连接或安装 ComfyUI" },
  { id: "models", name: "模型资料库", description: "选择模型与存放位置" },
  { id: "verify", name: "就绪检查", description: "确认文件与组件完整" },
  { id: "identity", name: "进入画布", description: "选择身份并阅读说明" },
];
export const titles: Record<Step, string> = {
  welcome: "本地创作，从这里开始。",
  comfy: "连接你的生成引擎。",
  models: "给模型一个合适的位置。",
  verify: "检查最后一块拼图。",
  identity: "你的画布，准备就绪。",
};
export const subtitles: Record<Step, string> = {
  welcome:
    "我们会逐步准备运行环境、模型和创作入口。进度保存在本机，可以随时回来继续。",
  comfy: "已有 ComfyUI 可以直接连接；没有安装，也可以在这里下载和准备。",
  models: "从 ai-go-play 分享选择需要的模型，导入默认位置或你指定的磁盘。",
  verify: "逐项校验所选模型，再检查工作流组件。缺少的文件会在这里明确列出。",
  identity:
    "连接亦可账号，或以游客身份开始本地创作。你的素材不会因为登录自动上传。",
};
