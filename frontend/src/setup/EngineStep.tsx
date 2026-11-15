import {
  ArrowRight,
  Check,
  CircuitBoard,
  Download,
  ExternalLink,
  FolderOpen,
  HardDrive,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import type { OnboardingView } from "./useOnboarding";
import { api } from "../api";

export default function EngineStep({ view }: { view: OnboardingView }) {
  const {
    state,
    comfy,
    candidates,
    scanned,
    scanning,
    installPath,
    setInstallPath,
    manualPath,
    setManualPath,
    port,
    setPort,
    setPicker,
    busy,
    refreshComfy,
    act,
    job,
    scanComfy,
    selectComfy,
  } = view;
  return (
    <>
      <div className="setup-section-row">
        <h2>
          <CircuitBoard size={20} />
          本机 ComfyUI
        </h2>
        <button
          className="setup-text-button"
          disabled={scanning || busy}
          onClick={() => void scanComfy()}
        >
          <RefreshCw size={16} className={scanning ? "setup-spin" : ""} />
          {scanning ? "正在扫描" : "重新扫描"}
        </button>
      </div>
      {scanning && (
        <div className="setup-scanning">
          <LoaderCircle className="setup-spin" />
          <span>正在检查常用安装位置…</span>
        </div>
      )}
      {candidates.map((c) => (
        <button
          key={c.comfy_path}
          className={`setup-installation ${comfy?.installation?.comfy_path === c.comfy_path ? "selected" : ""}`}
          onClick={() => void selectComfy(c.path)}
          disabled={busy}
        >
          <CircuitBoard size={23} />
          <span>
            <strong>{c.name}</strong>
            <small>{c.path}</small>
          </span>
          <span className="setup-selection-dot">
            {comfy?.installation?.comfy_path === c.comfy_path && (
              <Check size={13} />
            )}
          </span>
        </button>
      ))}
      {scanned && !scanning && !candidates.length && (
        <div className="setup-empty-inline">
          <HardDrive size={24} />
          <span>
            常用位置中未发现 ComfyUI。可以指定已有目录，或在下方安装。
          </span>
        </div>
      )}
      <div className="setup-field">
        <label htmlFor="comfy-path">已有安装目录</label>
        <div className="setup-path-row">
          <input
            id="comfy-path"
            value={manualPath || comfy?.installation_path || ""}
            onChange={(e) => setManualPath(e.target.value)}
            placeholder="选择 ComfyUI 或便携版目录"
          />
          <button
            aria-label="浏览 ComfyUI 安装目录"
            onClick={() => setPicker("comfy")}
          >
            <FolderOpen size={18} />
          </button>
          <button
            disabled={busy || !manualPath}
            onClick={() => void selectComfy(manualPath)}
          >
            连接目录
          </button>
        </div>
      </div>
      <div className="setup-engine-status">
        <span
          className={
            comfy && ["running", "external"].includes(comfy.status)
              ? "setup-good"
              : ""
          }
        >
          <span className="setup-status-dot" />
          {comfy && ["running", "external"].includes(comfy.status)
            ? "引擎已连接"
            : comfy?.status === "starting"
              ? "引擎正在启动…"
              : comfy?.installation
                ? "已选择，等待启动"
                : "等待选择引擎"}
        </span>
        <div>
          <label className="setup-port">
            端口
            <input
              type="number"
              value={port}
              min={1024}
              max={65535}
              aria-label="ComfyUI 端口"
              onChange={(e) => setPort(Number(e.target.value))}
            />
          </label>
          <button
            className="btn setup-secondary"
            disabled={busy || !comfy?.can_start}
            onClick={() =>
              void act(async () => {
                await api("/api/comfy/start", { method: "POST" });
                await refreshComfy();
              })
            }
          >
            启动 ComfyUI
            <ArrowRight size={15} />
          </button>
        </div>
      </div>
      {comfy?.error && comfy.status !== "external" && (
        <p className="setup-soft-note">{comfy.error}</p>
      )}
      <div className="setup-install-new">
        <div>
          <h2>还没有 ComfyUI？</h2>
          <p>
            自动下载官方 NVIDIA 便携版（约 1.93 GiB），校验后解压到专用目录。
          </p>
        </div>
        <div className="setup-path-row">
          <input
            aria-label="新 ComfyUI 安装位置"
            value={installPath}
            onChange={(e) => setInstallPath(e.target.value)}
          />
          <button
            aria-label="选择新的 ComfyUI 安装位置"
            onClick={() => setPicker("install")}
          >
            <FolderOpen size={18} />
          </button>
        </div>
        <div className="setup-inline-actions">
          <button
            className="btn setup-secondary"
            disabled={busy || !state.platform_supported}
            onClick={() =>
              void job("comfy-install", { destination: installPath, port })
            }
          >
            <Download size={16} />
            下载并安装
          </button>
          <a
            className="setup-external"
            href="https://docs.comfy.org/installation/comfyui_portable_windows"
            target="_blank"
            rel="noreferrer"
          >
            其他显卡与官方说明
            <ExternalLink size={14} />
          </a>
        </div>
        <small>
          建议预留 16 GiB 空间。已有目录和运行中的任务不会被替换。需要兼容 CUDA
          13 的 NVIDIA 驱动。
        </small>
      </div>
    </>
  );
}
