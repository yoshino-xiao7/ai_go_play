import {
  ArrowRight,
  AudioLines,
  CheckCircle2,
  Film,
  Image,
  Layers2,
  Sparkles,
} from "lucide-react";
import type { OnboardingView } from "./useOnboarding";
import { sizeText } from "../api";

export default function WelcomeStep({ view }: { view: OnboardingView }) {
  const { catalog } = view;
  return (
    <>
      <div className="setup-welcome-scene" aria-label="创作流程预览">
        <div className="setup-scene-toolbar">
          <span>
            <span />
            本地工作台
          </span>
          <span>图片 · 视频 · 声音</span>
        </div>
        <div className="setup-scene-nodes">
          <div className="setup-preview-node">
            <span className="setup-node-top">
              <Layers2 size={15} />
              素材与想法
            </span>
            <div className="setup-paper-lines">
              <i />
              <i />
              <i />
            </div>
            <small>从一段文字开始</small>
          </div>
          <span className="setup-node-wire">
            <ArrowRight size={17} />
          </span>
          <div className="setup-preview-node setup-preview-main">
            <span className="setup-node-top">
              <Sparkles size={15} />
              你的创作画布
            </span>
            <div className="setup-scene-grid">
              <Image size={27} />
              <Film size={27} />
              <AudioLines size={27} />
            </div>
            <small>连接素材，编排生成</small>
          </div>
          <span className="setup-node-wire">
            <ArrowRight size={17} />
          </span>
          <div className="setup-preview-node setup-preview-output">
            <CheckCircle2 size={29} />
            <strong>作品</strong>
            <small>保存在你的电脑</small>
          </div>
        </div>
        <div className="setup-scene-bottom">
          <span>无限画布</span>
          <span>本地生成</span>
          <span>自主分享</span>
        </div>
      </div>
      <div className="setup-welcome-facts">
        <div>
          <strong>01</strong>
          <span>连接本机引擎</span>
        </div>
        <div>
          <strong>02</strong>
          <span>导入并校验模型</span>
        </div>
        <div>
          <strong>03</strong>
          <span>选择身份，开始创作</span>
        </div>
      </div>
      <p className="setup-soft-note">
        模型按功能选择，无需一次下载全部。
        {catalog && (
          <>
            完整发布清单共 {catalog.files.length} 个文件，约{" "}
            {sizeText(catalog.total_bytes)}。
          </>
        )}
      </p>
    </>
  );
}
