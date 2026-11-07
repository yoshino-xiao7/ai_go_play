import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircuitBoard,
  Copy,
  ExternalLink,
  FolderOpen,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  ScanSearch,
  Server,
  Square,
  Terminal,
  X,
} from "lucide-react";
import { api, ApiError } from "./api";
import { Modal } from "./ui";
import "./comfy.css";

type ComfyInstallation = {
  path: string;
  comfy_path: string;
  python_path: string;
  kind: "portable" | "venv";
  name: string;
};

type ComfyStatus = {
  status:
    | "not_configured"
    | "stopped"
    | "starting"
    | "running"
    | "stopping"
    | "external"
    | "port_conflict"
    | "error";
  installation: ComfyInstallation | null;
  installation_path: string | null;
  port: number;
  base_url: string;
  managed: boolean;
  pid: number | null;
  can_start: boolean;
  can_stop: boolean;
  error: string | null;
  queue: { running: number; pending: number } | null;
  started_at: string | null;
};

type ComfyLogs = { lines: string[]; path: string | null; truncated: boolean };
type ScanResult = {
  installations: ComfyInstallation[];
  scanned_roots: string[];
};
type Action = "scan" | "save" | "start" | "stop" | null;

const stateLabels: Record<ComfyStatus["status"], string> = {
  not_configured: "等待配置",
  stopped: "已停止",
  starting: "正在启动",
  running: "已就绪",
  stopping: "正在停止",
  external: "外部实例已连接",
  port_conflict: "端口被占用",
  error: "启动遇到问题",
};

const stateDescriptions: Record<ComfyStatus["status"], string> = {
  not_configured: "扫描本机安装，或填写已有的 ComfyUI 目录。",
  stopped: "已选用本机安装，可以在这里启动服务。",
  starting: "正在加载运行环境，服务就绪后会自动更新状态。",
  running: "本地服务已响应，可以打开 ComfyUI 工作流界面。",
  stopping: "正在关闭工作台启动的服务进程。",
  external: "已连接到其他程序启动的 ComfyUI，可直接打开使用。",
  port_conflict: "当前端口正在被其他服务使用，请选择可用端口。",
  error: "查看启动日志，修正环境或路径后重新启动。",
};

const messageOf = (error: unknown) =>
  error instanceof Error ? error.message : String(error);

function samePath(first?: string | null, second?: string | null) {
  return (
    (first || "").replace(/[\\/]+$/, "").toLowerCase() ===
    (second || "").replace(/[\\/]+$/, "").toLowerCase()
  );
}

export default function ComfyPanel({ onClose }: { onClose: () => void }) {
  const [section, setSection] = useState<"setup" | "logs">("setup");
  const [status, setStatus] = useState<ComfyStatus | null>(null);
  const [installations, setInstallations] = useState<ComfyInstallation[]>([]);
  const [scannedRoots, setScannedRoots] = useState<string[]>([]);
  const [scanComplete, setScanComplete] = useState(false);
  const [scanPath, setScanPath] = useState("");
  const [showScanPath, setShowScanPath] = useState(false);
  const [installationPath, setInstallationPath] = useState("");
  const [port, setPort] = useState("8188");
  const [action, setAction] = useState<Action>(null);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [logError, setLogError] = useState("");
  const [logs, setLogs] = useState<ComfyLogs | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [confirmStop, setConfirmStop] = useState(false);
  const [copied, setCopied] = useState(false);
  const mounted = useRef(true);
  const formEdited = useRef(false);
  const statusSequence = useRef(0);
  const activeStatus = useRef<ComfyStatus | null>(null);
  const logView = useRef<HTMLPreElement>(null);
  const panelView = useRef<HTMLDivElement>(null);
  const followLogs = useRef(true);
  const copiedTimeout = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  const applyStatus = useCallback((next: ComfyStatus) => {
    if (!mounted.current) return;
    activeStatus.current = next;
    setStatus(next);
    setLoadError("");
    if (!formEdited.current) {
      setInstallationPath(next.installation_path || "");
      setPort(String(next.port));
    }
  }, []);

  const refresh = useCallback(async () => {
    const sequence = ++statusSequence.current;
    const results = await Promise.allSettled([
      api<ComfyStatus>("/api/comfy", { signal: AbortSignal.timeout(7000) }),
      api<ComfyLogs>("/api/comfy/logs?limit=200", {
        signal: AbortSignal.timeout(7000),
      }),
    ]);
    if (!mounted.current) return;
    const [stateResult, logResult] = results;
    if (sequence === statusSequence.current) {
      if (stateResult.status === "fulfilled") applyStatus(stateResult.value);
      else setLoadError(messageOf(stateResult.reason));
    }
    if (logResult.status === "fulfilled") {
      setLogs((current) =>
        JSON.stringify(current) === JSON.stringify(logResult.value)
          ? current
          : logResult.value,
      );
      setLogError("");
    } else setLogError(messageOf(logResult.reason));
  }, [applyStatus]);

  useEffect(() => {
    mounted.current = true;
    let disposed = false;
    panelView.current
      ?.closest<HTMLElement>('[role="dialog"]')
      ?.focus({ preventScroll: true });
    if (panelView.current) panelView.current.scrollTop = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      await refresh();
      if (disposed || !mounted.current) return;
      const changing = ["starting", "stopping"].includes(
        activeStatus.current?.status || "",
      );
      timer = setTimeout(() => void poll(), changing ? 1000 : 3000);
    };
    void poll();
    return () => {
      disposed = true;
      mounted.current = false;
      clearTimeout(timer);
      clearTimeout(copiedTimeout.current);
    };
  }, [refresh]);

  useEffect(() => {
    if (followLogs.current && logView.current)
      logView.current.scrollTop = logView.current.scrollHeight;
  }, [logs, section]);

  const validPort =
    Number.isInteger(Number(port)) &&
    Number(port) >= 1024 &&
    Number(port) <= 65535;
  const unsaved =
    !!status &&
    (!samePath(installationPath.trim(), status.installation_path) ||
      Number(port) !== status.port);
  const transitioning =
    status?.status === "starting" || status?.status === "stopping";
  const settingsLocked =
    !!status &&
    status.managed &&
    ["running", "starting", "stopping"].includes(status.status);
  const busy = action !== null;
  const online = status?.status === "running" || status?.status === "external";
  const error = actionError || loadError || status?.error;

  const saveSettings = async (path = installationPath) => {
    if (!path.trim()) {
      setActionError("请填写 ComfyUI 安装目录。");
      return;
    }
    if (!validPort) {
      setActionError("端口需为 1024 至 65535 之间的整数。");
      return;
    }
    setAction("save");
    setActionError("");
    setFeedback("");
    try {
      const next = await api<ComfyStatus>("/api/comfy/settings", {
        method: "PUT",
        body: JSON.stringify({
          installation_path: path.trim(),
          port: Number(port),
        }),
      });
      if (!mounted.current) return;
      statusSequence.current += 1;
      formEdited.current = false;
      applyStatus(next);
      setFeedback("安装路径与端口已保存。");
    } catch (caught) {
      if (mounted.current) setActionError(messageOf(caught));
    } finally {
      if (mounted.current) setAction(null);
    }
  };

  const scan = async (path?: string) => {
    if (path !== undefined && !path.trim()) {
      setActionError("请填写要扫描的文件夹路径。");
      return;
    }
    setAction("scan");
    setActionError("");
    setFeedback("");
    try {
      const result = await api<ScanResult>("/api/comfy/scan", {
        method: "POST",
        body: JSON.stringify(path ? { path: path.trim() } : {}),
      });
      if (!mounted.current) return;
      setInstallations((current) => {
        const candidates = path
          ? [...current, ...result.installations]
          : result.installations;
        return candidates.filter(
          (candidate, index) =>
            candidates.findIndex((item) =>
              samePath(item.path, candidate.path),
            ) === index,
        );
      });
      setScannedRoots((current) =>
        path
          ? Array.from(new Set([...current, ...result.scanned_roots]))
          : result.scanned_roots,
      );
      setScanComplete(true);
      if (path)
        setFeedback(
          result.installations.length
            ? `在该目录找到 ${result.installations.length} 个安装。`
            : "该目录未发现可用安装，可在下方直接填写安装路径。",
        );
    } catch (caught) {
      if (mounted.current) setActionError(messageOf(caught));
    } finally {
      if (mounted.current) setAction(null);
    }
  };

  const changeService = async (operation: "start" | "stop", force = false) => {
    setAction(operation);
    setActionError("");
    setFeedback("");
    try {
      const next = await api<ComfyStatus>(`/api/comfy/${operation}`, {
        method: "POST",
        body: JSON.stringify(operation === "stop" ? { force } : {}),
      });
      if (!mounted.current) return;
      statusSequence.current += 1;
      applyStatus(next);
      setConfirmStop(false);
      followLogs.current = true;
      void refresh();
    } catch (caught) {
      if (!mounted.current) return;
      if (
        caught instanceof ApiError &&
        (caught.detail as { code?: string })?.code === "comfy_queue_busy"
      ) {
        setConfirmStop(true);
      } else setActionError(messageOf(caught));
      void refresh();
    } finally {
      if (mounted.current) setAction(null);
    }
  };

  const copyLogs = async () => {
    try {
      await navigator.clipboard.writeText(logs?.lines.join("\n") || "");
      setCopied(true);
      clearTimeout(copiedTimeout.current);
      copiedTimeout.current = setTimeout(() => setCopied(false), 2500);
    } catch {
      setActionError("日志复制失败，可以直接选择日志文字复制。");
    }
  };

  return (
    <Modal title="ComfyUI 本地服务" onClose={onClose} wide className="management-modal comfy-modal">
      <div className="management-layout">
      <nav className="management-nav" aria-label="本地服务设置分类">
        <span className="management-nav-label">本地生成</span>
        <button aria-current={section === "setup" ? "page" : undefined} onClick={() => setSection("setup")}><CircuitBoard size={18} />安装与启动</button>
        <button aria-current={section === "logs" ? "page" : undefined} onClick={() => setSection("logs")}><Terminal size={18} />运行日志</button>
        <p>连接本机 ComfyUI，管理创作所需的生成服务。</p>
      </nav>
      <div className="comfy-panel" ref={panelView}>
        <div className="comfy-service-card">
          <div className="comfy-service-heading">
            <div className="comfy-service-icon">
              <CircuitBoard size={30} strokeWidth={1.4} />
            </div>
            <div>
              <div className="comfy-service-name">
                <h2>ComfyUI</h2>
                <span className={`comfy-state ${status?.status || "is-loading"}`}>
                  <i />
                  {status ? stateLabels[status.status] : "正在连接"}
                </span>
              </div>
              <p>
                {status
                  ? stateDescriptions[status.status]
                  : "正在读取本机服务配置与运行状态。"}
              </p>
            </div>
          </div>
          <div className="comfy-service-controls">
            {online && (
              <a
                className="comfy-button secondary"
                href={status.base_url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={14} />
                打开 ComfyUI
              </a>
            )}
            {status?.can_stop ? (
              <button
                className="comfy-button stop"
                onClick={() => void changeService("stop")}
                disabled={busy || status.status === "stopping"}
              >
                {action === "stop" || status.status === "stopping" ? (
                  <LoaderCircle className="spin" size={14} />
                ) : (
                  <Square size={13} />
                )}
                停止服务
              </button>
            ) : (
              <button
                className="comfy-button primary"
                onClick={() => void changeService("start")}
                disabled={!status?.can_start || busy || unsaved || !validPort}
              >
                {action === "start" || status?.status === "starting" ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Play size={14} />
                )}
                {status?.status === "starting" ? "正在启动" : "启动服务"}
              </button>
            )}
          </div>
          <div className="comfy-service-meta">
            <span>
              <Server size={12} />
              {status?.base_url || `http://127.0.0.1:${port || "8188"}`}
            </span>
            <span>
              <i className={status?.managed ? "managed" : ""} />
              {status?.managed
                ? "工作台管理"
                : status?.status === "external"
                  ? "外部启动"
                  : "本机运行"}
            </span>
            {status?.queue && (
              <span>
                {status.queue.running} 个运行中 · {status.queue.pending}{" "}
                个排队中
              </span>
            )}
            {status?.pid && (
              <span className="comfy-process-id">PID {status.pid}</span>
            )}
            <button
              className="comfy-refresh"
              title="刷新服务状态"
              aria-label="刷新服务状态"
              disabled={refreshing}
              onClick={async () => {
                setRefreshing(true);
                await refresh();
                if (mounted.current) setRefreshing(false);
              }}
            >
              <RefreshCw size={12} className={refreshing ? "spin" : ""} />
              刷新
            </button>
          </div>
        </div>

        {error && (
          <div className="comfy-message error" role="alert">
            <AlertCircle size={16} />
            <span>{error}</span>
            {actionError && (
              <button title="关闭错误提示" onClick={() => setActionError("")}>
                <X size={13} />
              </button>
            )}
          </div>
        )}
        {confirmStop && (
          <div className="comfy-stop-confirm">
            <AlertCircle size={18} />
            <div>
              <strong>ComfyUI 中还有生成任务</strong>
              <p>
                停止服务会中断正在运行的任务。确认后将关闭本工作台启动的进程。
              </p>
            </div>
            <button
              className="comfy-button secondary"
              onClick={() => setConfirmStop(false)}
              disabled={busy}
            >
              继续运行
            </button>
            <button
              className="comfy-button stop"
              onClick={() => void changeService("stop", true)}
              disabled={busy}
            >
              {action === "stop" ? "正在停止" : "停止并中断任务"}
            </button>
          </div>
        )}

        <div className="comfy-columns">
          <section className="comfy-setup" hidden={section !== "setup"}>
            <div className="comfy-section-heading">
              <h3>本机安装</h3>
              <button
                className="comfy-button compact secondary"
                onClick={() => void scan()}
                disabled={busy}
              >
                {action === "scan" ? (
                  <LoaderCircle size={13} className="spin" />
                ) : (
                  <ScanSearch size={14} />
                )}
                {action === "scan"
                  ? "正在扫描"
                  : scanComplete
                    ? "重新扫描"
                    : "扫描本机"}
              </button>
            </div>
            <div className="comfy-installations">
              {installations.length ? (
                installations.map((installation) => (
                  <button
                    key={installation.path}
                    className={`comfy-installation ${samePath(installation.path, status?.installation_path) ? "selected" : ""}`}
                    disabled={busy || settingsLocked}
                    onClick={() => void saveSettings(installation.path)}
                  >
                    <span className="comfy-installation-icon">
                      <FolderOpen size={19} strokeWidth={1.5} />
                    </span>
                    <span className="comfy-installation-info">
                      <strong>
                        {installation.name || "ComfyUI"}
                        <small>
                          {installation.kind === "portable"
                            ? "便携版"
                            : "独立环境"}
                        </small>
                      </strong>
                      <span title={installation.path}>{installation.path}</span>
                    </span>
                    <span className="comfy-installation-check">
                      {samePath(
                        installation.path,
                        status?.installation_path,
                      ) ? (
                        <Check size={14} />
                      ) : (
                        <ChevronRight size={14} />
                      )}
                    </span>
                  </button>
                ))
              ) : (
                <div className="comfy-scan-empty">
                  <FolderOpen size={25} strokeWidth={1.3} />
                  <div>
                    <strong>
                      {scanComplete
                        ? "暂未发现本机安装"
                        : status?.installation
                          ? "已选用本机安装"
                          : "找到你的 ComfyUI"}
                    </strong>
                    <p>
                      {scanComplete
                        ? "可指定其他文件夹扫描，或手动填写安装目录。"
                        : status?.installation
                          ? status.installation.path
                          : "扫描常用位置中的便携版与独立 Python 环境。"}
                    </p>
                  </div>
                </div>
              )}
            </div>
            <button
              className="comfy-scan-path-toggle"
              aria-expanded={showScanPath}
              onClick={() => setShowScanPath((value) => !value)}
            >
              {showScanPath ? (
                <ChevronDown size={13} />
              ) : (
                <ChevronRight size={13} />
              )}
              添加扫描目录
            </button>
            {showScanPath && (
              <form
                className="comfy-scan-path"
                onSubmit={(event) => {
                  event.preventDefault();
                  void scan(scanPath);
                }}
              >
                <label htmlFor="comfy-scan-path">文件夹路径</label>
                <div>
                  <input
                    id="comfy-scan-path"
                    value={scanPath}
                    onChange={(event) => setScanPath(event.target.value)}
                    placeholder="例如 D:\AI"
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <button
                    className="comfy-button secondary compact"
                    type="submit"
                    disabled={busy || !scanPath.trim()}
                  >
                    <ScanSearch size={14} />
                    扫描目录
                  </button>
                </div>
              </form>
            )}
            {scannedRoots.length > 0 && (
              <details className="comfy-scanned-roots">
                <summary>已扫描 {scannedRoots.length} 个位置</summary>
                {scannedRoots.map((root) => (
                  <span key={root} title={root}>
                    {root}
                  </span>
                ))}
              </details>
            )}

            <form
              className="comfy-settings-form"
              onSubmit={(event) => {
                event.preventDefault();
                void saveSettings();
              }}
            >
              <div className="comfy-section-heading">
                <h3>启动配置</h3>
                {settingsLocked && <span>停止服务后可修改</span>}
              </div>
              <label htmlFor="comfy-installation-path">ComfyUI 安装目录</label>
              <input
                id="comfy-installation-path"
                value={installationPath}
                onChange={(event) => {
                  formEdited.current = true;
                  setInstallationPath(event.target.value);
                  setFeedback("");
                }}
                placeholder="例如 D:\AI\ComfyUI_windows_portable"
                disabled={settingsLocked || busy}
                spellCheck={false}
                autoComplete="off"
              />
              <div className="comfy-port-row">
                <label htmlFor="comfy-port">
                  服务端口
                  <input
                    id="comfy-port"
                    type="number"
                    inputMode="numeric"
                    min={1024}
                    max={65535}
                    value={port}
                    onChange={(event) => {
                      formEdited.current = true;
                      setPort(event.target.value);
                      setFeedback("");
                    }}
                    disabled={settingsLocked || busy}
                  />
                </label>
                <button
                  className="comfy-button secondary"
                  type="submit"
                  disabled={
                    settingsLocked ||
                    busy ||
                    !installationPath.trim() ||
                    !validPort ||
                    (!unsaved && !!status?.installation)
                  }
                >
                  {action === "save" ? (
                    <LoaderCircle size={14} className="spin" />
                  ) : (
                    <Save size={14} />
                  )}
                  {action === "save" ? "保存中" : "保存配置"}
                </button>
              </div>
              {!validPort && (
                <p className="comfy-form-note">
                  端口需为 1024 至 65535 之间的整数。
                </p>
              )}
              {unsaved && validPort && (
                <p className="comfy-form-note">
                  配置有修改，保存后可启动服务。
                </p>
              )}
              {feedback && (
                <p className="comfy-form-feedback" role="status">
                  <Check size={13} />
                  {feedback}
                </p>
              )}
              {status?.installation?.python_path && (
                <div className="comfy-python-path">
                  <span>Python 环境</span>
                  <code title={status.installation.python_path}>
                    {status.installation.python_path}
                  </code>
                </div>
              )}
            </form>
          </section>

          <section className="comfy-logs" hidden={section !== "logs"}>
            <div className="comfy-section-heading">
              <h3>
                <Terminal size={15} />
                服务日志
              </h3>
              <button
                className="comfy-log-copy"
                title="复制日志"
                onClick={() => void copyLogs()}
                disabled={!logs?.lines.length}
              >
                {copied ? <Check size={13} /> : <Copy size={13} />}
                {copied ? "已复制" : "复制"}
              </button>
            </div>
            {logError && (
              <p className="comfy-log-error">
                <AlertCircle size={13} />
                {logError}
              </p>
            )}
            {logs?.lines.length ? (
              <pre
                ref={logView}
                className="comfy-log-output"
                tabIndex={0}
                aria-label="ComfyUI 服务日志"
                onScroll={(event) => {
                  const element = event.currentTarget;
                  followLogs.current =
                    element.scrollHeight -
                      element.scrollTop -
                      element.clientHeight <
                    40;
                }}
              >
                {logs.lines.join("\n")}
              </pre>
            ) : (
              <div className="comfy-log-empty">
                {transitioning ? (
                  <LoaderCircle size={26} className="spin" />
                ) : (
                  <Terminal size={26} strokeWidth={1.2} />
                )}
                <p>
                  {transitioning
                    ? "等待进程输出…"
                    : status?.status === "external"
                      ? "外部实例的日志请在其启动程序中查看"
                      : "启动服务后，在这里查看运行日志"}
                </p>
              </div>
            )}
            <div className="comfy-log-footer">
              <span title={logs?.path || undefined}>
                {logs?.path || "日志保存在本机"}
              </span>
              {logs?.truncated && <small>最近 200 行</small>}
            </div>
          </section>
        </div>
      </div>
      </div>
      <footer className="comfy-panel-footer">
        <span>
          <CircuitBoard size={13} />
          本地生成服务
        </span>
        {online && (
          <a href={status.base_url} target="_blank" rel="noreferrer">
            前往工作流界面
            <ArrowUpRight size={13} />
          </a>
        )}
        <button className="comfy-button secondary compact" onClick={onClose}>
          返回工作台
        </button>
      </footer>
    </Modal>
  );
}
