import {
  ArrowRight,
  Check,
  ChevronRight,
  ExternalLink,
  FileCheck2,
  RefreshCw,
} from "lucide-react";
import type { OnboardingView } from "./useOnboarding";
import { api } from "../api";

export default function ChecksStep({ view }: { view: OnboardingView }) {
  const {
    state,
    catalog,
    comfy,
    readiness,
    showMissing,
    setShowMissing,
    busy,
    refreshComfy,
    checkReady,
    act,
    job,
    validationReady,
    missing,
  } = view;
  return (
    <>
      <div className="setup-check-hero">
        <div
          className={`setup-check-orbit ${validationReady && readiness?.ready ? "done" : ""}`}
        >
          <FileCheck2 size={40} />
        </div>
        <div>
          <h2>
            {validationReady && readiness?.ready
              ? "所选功能已经准备好"
              : "一起确认，生成前的准备"}
          </h2>
          <p>
            {state.validation
              ? `${state.validation.verified} / ${state.validation.total} 个文件通过 SHA256 校验`
              : "完整校验会读取模型内容。大模型较多时，需要等待一段时间。"}
          </p>
        </div>
      </div>
      <div className="setup-check-row">
        <div>
          <strong>模型文件</strong>
          <span>核对文件、大小和 SHA256</span>
        </div>
        <span className={validationReady ? "setup-good" : "setup-muted"}>
          {validationReady ? (
            <>
              <Check size={15} />
              已通过
            </>
          ) : (
            "等待完整校验"
          )}
        </span>
        <button
          className="btn setup-secondary"
          disabled={busy}
          onClick={() => void job("verify")}
        >
          完整校验
          <ArrowRight size={15} />
        </button>
      </div>
      <div className="setup-check-row">
        <div>
          <strong>运行组件</strong>
          <span>安装所选组件；空闲的托管引擎会自动重启</span>
        </div>
        <button
          className="btn setup-secondary"
          disabled={busy || !validationReady}
          onClick={() => void job("runtimes")}
        >
          安装 / 连接组件
        </button>
      </div>
      <div className="setup-check-row">
        <div>
          <strong>ComfyUI 节点</strong>
          <span>新增组件后重新启动引擎</span>
        </div>
        <div className="setup-inline-actions">
          {comfy?.can_stop && (
            <button
              className="setup-text-button"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api("/api/comfy/stop", {
                    method: "POST",
                    body: JSON.stringify({ force: false }),
                  });
                  await refreshComfy();
                })
              }
            >
              停止引擎
            </button>
          )}
          {comfy?.can_start && (
            <button
              className="setup-text-button"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await api("/api/comfy/start", { method: "POST" });
                  await refreshComfy();
                })
              }
            >
              启动引擎
            </button>
          )}
          <button
            className="btn setup-secondary"
            disabled={busy}
            onClick={() => void act(checkReady)}
          >
            <RefreshCw size={15} />
            检查组件
          </button>
        </div>
      </div>
      {readiness?.packs.map((p) => (
        <div className="setup-readiness-row" key={p.pack}>
          <span>{catalog?.packs.find((c) => c.id === p.pack)?.name}</span>
          <span className={p.ready ? "setup-good" : "setup-warning"}>
            {p.ready ? (
              <>
                <Check size={14} />
                组件就绪
              </>
            ) : (
              p.missing_nodes.join("、")
            )}
          </span>
        </div>
      ))}
      {readiness?.packs.some((p) => !p.ready) && (
        <p className="setup-soft-note">
          先点击安装 / 连接组件，再重启并检查。已有旧节点需要升级时，请查看{" "}
          <a
            href="https://github.com/yoshino-xiao7/ai_go_play#本地模型与-comfyui-配置指南"
            target="_blank"
            rel="noreferrer"
          >
            项目安装指引
          </a>
          。已安装的外部 ComfyUI
          需要在其原窗口重启；不使用的功能可返回模型步骤取消选择。
        </p>
      )}
      <div className="setup-missing-header">
        <button
          onClick={() => setShowMissing(!showMissing)}
          aria-expanded={showMissing}
        >
          <ChevronRight size={16} className={showMissing ? "expanded" : ""} />
          {missing.length
            ? `${missing.length} 个待补齐 / 待校验文件`
            : "没有发现缺失文件"}
        </button>
        <a
          className="setup-external"
          href={catalog?.share.url}
          target="_blank"
          rel="noreferrer"
        >
          前往夸克下载
          <ExternalLink size={14} />
        </a>
        {catalog?.mirrors?.map((mirror) => (
          <a key={mirror.id} className="setup-external" href={mirror.url} target="_blank" rel="noreferrer">
            前往{mirror.name}下载<ExternalLink size={14} />
          </a>
        ))}
      </div>
      {showMissing && (
        <div className="setup-missing-list">
          {missing.map((f) => (
            <div key={f.path}>
              <span>
                <strong>{f.path.split("/").pop()}</strong>
                <small>{f.path}</small>
                <small>
                  网盘位置：{state.share_scan?.files.find((remote) => remote.path === f.path)?.remote_path
                    || catalog?.files.find((item) => item.path === f.path)?.download_path
                    || `${f.packs[0]}/models/${f.path}`}
                </small>
              </span>
              <em>
                {f.status === "mismatch"
                  ? "内容不匹配"
                  : f.status === "unreadable"
                    ? "无法读取"
                    : "缺失"}
              </em>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
