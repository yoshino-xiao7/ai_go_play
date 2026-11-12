import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  Copy,
  ExternalLink,
  LoaderCircle,
  LogOut,
  RefreshCw,
  Share2,
  Trash2,
} from "lucide-react";

import { api } from "./api";
import type { Project } from "./types";
import { Modal } from "./ui";
import "./share-panel.css";

type Viewport = { x: number; y: number; zoom: number };

type SetuUser = { id: number; nickname?: string; avatarUrl?: string };

type ShareStatus = {
  connected: boolean;
  user: SetuUser | null;
  siteBase: string;
  apiBase: string;
};

type ShareRow = {
  share_id: number;
  slug: string;
  title: string;
  visibility: string;
  quality: string;
  revision: number;
  media_count: number;
  size_bytes: number;
  url: string;
  updated_at: string;
};

type ShareJob = {
  state: "running" | "done" | "failed";
  phase: string;
  uploaded: number;
  total: number;
  error?: string | null;
  url?: string | null;
};

type ProjectShareState = { share: ShareRow | null; job: ShareJob | null };

type ConnectState = {
  state: "pending" | "approved" | "failed" | "expired";
  user?: SetuUser | null;
  error?: string | null;
  seconds_left: number;
};

type Props = {
  project: Project;
  onFlush: () => Promise<void>;
  getViewport: () => Viewport;
  onClose: () => void;
  onNotice: (message: string, error?: boolean) => void;
};

const phaseText: Record<string, string> = {
  snapshot: "生成画布快照",
  prepare: "准备上传",
  upload: "上传媒体",
  commit: "写入在线画布",
  done: "完成",
};

function errorText(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export default function SharePanel({
  project,
  onFlush,
  getViewport,
  onClose,
  onNotice,
}: Props) {
  const [status, setStatus] = useState<ShareStatus | null>(null);
  const [state, setState] = useState<ProjectShareState>({ share: null, job: null });
  const [title, setTitle] = useState(project.name);
  const [visibility, setVisibility] = useState<"link" | "login">("link");
  const [quality, setQuality] = useState<"preview" | "full">("preview");
  const [connecting, setConnecting] = useState<{ requestId: string; url: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [copied, setCopied] = useState(false);
  const previousJob = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    const [nextStatus, nextState] = await Promise.all([
      api<ShareStatus>("/api/share/status"),
      api<ProjectShareState>(`/api/projects/${project.id}/share`),
    ]);
    setStatus(nextStatus);
    setState(nextState);
    return nextState;
  }, [project.id]);

  useEffect(() => {
    void refresh().then((next) => {
      if (next.share) {
        setTitle(next.share.title);
        setVisibility(next.share.visibility === "LOGIN" ? "login" : "link");
        setQuality(next.share.quality === "full" ? "full" : "preview");
      }
    }).catch((reason) => setError(errorText(reason)));
  }, [refresh]);

  useEffect(() => {
    if (state.job?.state !== "running") return;
    const timer = window.setInterval(() => {
      void refresh().catch(() => {});
    }, 900);
    return () => window.clearInterval(timer);
  }, [refresh, state.job?.state]);

  useEffect(() => {
    const current = state.job?.state;
    if (!current) return;
    if (previousJob.current === "running" && current === "done") {
      onNotice("已分享到亦可");
      void refresh().catch(() => {});
    }
    if (previousJob.current === "running" && current === "failed") {
      setError(state.job?.error || "分享失败，请稍后重试。");
    }
    previousJob.current = current;
  }, [onNotice, refresh, state.job?.error, state.job?.state]);

  useEffect(() => {
    if (!connecting) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const result = await api<ConnectState>(`/api/share/connect/${connecting.requestId}`);
        if (cancelled) return;
        if (result.state === "approved") {
          setConnecting(null);
          await refresh();
          onNotice("已连接亦可账号");
        } else if (result.state !== "pending") {
          setConnecting(null);
          setError(result.error || "授权已超时，请重新发起连接。");
        }
      } catch (reason) {
        if (!cancelled) {
          setConnecting(null);
          setError(errorText(reason));
        }
      }
    };
    void tick();
    const timer = window.setInterval(() => {
      void tick();
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [connecting, onNotice, refresh]);

  const connect = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ request_id: string; authorize_url: string }>("/api/share/connect", {
        method: "POST",
      });
      setConnecting({ requestId: result.request_id, url: result.authorize_url });
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/api/share/disconnect", { method: "POST" });
      await refresh();
      onNotice("已断开亦可账号");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    setBusy(true);
    setError("");
    try {
      await onFlush();
      const fresh = await api<Project>(`/api/projects/${project.id}`);
      previousJob.current = "running";
      await api(`/api/projects/${project.id}/share`, {
        method: "POST",
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          title: title.trim() || project.name,
          visibility,
          quality,
          canvas_revision: fresh.revision,
          viewport: getViewport(),
        }),
      });
      await refresh();
    } catch (reason) {
      previousJob.current = null;
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await api(`/api/projects/${project.id}/share`, { method: "DELETE" });
      setConfirmingDelete(false);
      await refresh();
      onNotice("已删除在线分享");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("复制失败，请手动选择链接。");
    }
  };

  const publishing = busy || state.job?.state === "running";
  const share = state.share;

  return (
    <Modal title="分享到亦可" onClose={onClose} wide>
      <div className="share-panel-body">
        {status === null ? (
          <p className="share-muted">
            <LoaderCircle className="spin" size={15} /> 正在读取连接状态…
          </p>
        ) : !status.connected ? (
          <section className="share-section">
            <h3>先连接亦可账号</h3>
            <p>在浏览器完成登录与授权后，本地工作台只会获得画布分享权限，可随时在亦可个人页撤销。</p>
            {connecting ? (
              <div className="share-wait">
                <LoaderCircle className="spin" size={16} />
                <span>等待浏览器确认…</span>
                <a href={connecting.url} target="_blank" rel="noreferrer">没打开浏览器？</a>
              </div>
            ) : (
              <button className="button primary" onClick={() => void connect()} disabled={busy}>
                在浏览器登录亦可
              </button>
            )}
          </section>
        ) : (
          <>
            <section className="share-account">
              {status.user?.avatarUrl ? (
                <img className="share-avatar" src={status.user.avatarUrl} alt="" />
              ) : (
                <span className="share-avatar share-avatar-fallback">
                  <Share2 size={16} />
                </span>
              )}
              <div className="share-account-text">
                <strong>{status.user?.nickname || "亦可账号"}</strong>
                <span>{status.siteBase}</span>
              </div>
              <button className="button ghost compact" onClick={() => void disconnect()} disabled={busy}>
                <LogOut size={14} /> 断开
              </button>
            </section>

            <section className="share-section">
              <label className="share-field">
                <span>分享标题</span>
                <input
                  value={title}
                  maxLength={60}
                  placeholder="给这份画布起个名字"
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <div className="share-field">
                <span>谁可以看</span>
                <div className="share-segment" role="group" aria-label="可见性">
                  <button
                    className={visibility === "link" ? "active" : ""}
                    onClick={() => setVisibility("link")}
                  >
                    拿到链接即可查看
                  </button>
                  <button
                    className={visibility === "login" ? "active" : ""}
                    onClick={() => setVisibility("login")}
                  >
                    需登录亦可账号
                  </button>
                </div>
              </div>
              <div className="share-field">
                <span>画质</span>
                <div className="share-segment" role="group" aria-label="画质">
                  <button
                    className={quality === "preview" ? "active" : ""}
                    onClick={() => setQuality("preview")}
                  >
                    预览画质
                  </button>
                  <button
                    className={quality === "full" ? "active" : ""}
                    onClick={() => setQuality("full")}
                  >
                    高画质
                  </button>
                </div>
                <small>高画质会上传图片原件与视频原片，体积更大、上传更久。</small>
              </div>
              <button className="button primary" onClick={() => void publish()} disabled={publishing}>
                {publishing ? <LoaderCircle className="spin" size={15} /> : <Share2 size={15} />}
                {share ? "更新分享" : "分享到亦可"}
              </button>
            </section>

            {state.job?.state === "running" && (
              <div className="share-progress">
                <span>
                  {phaseText[state.job.phase] || "处理中"}
                  {state.job.total > 0 ? ` · ${state.job.uploaded}/${state.job.total}` : ""}
                </span>
                <progress max={state.job.total || 1} value={state.job.uploaded} />
              </div>
            )}

            {share && (
              <section className="share-result">
                <div className="share-result-head">
                  <strong>在线链接</strong>
                  <span className={`share-chip ${share.visibility === "LOGIN" ? "secure" : ""}`}>
                    {share.visibility === "LOGIN" ? "需登录" : "链接可见"}
                  </span>
                </div>
                <div className="share-link">
                  <code>{share.url}</code>
                  <button className="icon-button" onClick={() => void copy(share.url)} aria-label="复制链接">
                    {copied ? <Check size={15} /> : <Copy size={15} />}
                  </button>
                  <a className="button ghost compact" href={share.url} target="_blank" rel="noreferrer">
                    <ExternalLink size={14} /> 打开
                  </a>
                </div>
                <small>
                  最近更新 {share.updated_at} · {share.media_count} 个媒体 · {Math.max(1, Math.round(share.size_bytes / 1024 ** 2))} MB
                </small>
                <div className="share-result-actions">
                  <button className="button ghost compact" onClick={() => void refresh()} disabled={busy}>
                    <RefreshCw size={14} /> 刷新状态
                  </button>
                  <button className="button danger compact" onClick={() => setConfirmingDelete(true)} disabled={busy}>
                    <Trash2 size={14} /> 删除分享
                  </button>
                </div>
                {confirmingDelete && (
                  <div className="share-confirm">
                    <span>删除后链接立即失效，本地画布不受影响。</span>
                    <button className="button danger compact" onClick={() => void remove()} disabled={busy}>
                      确认删除
                    </button>
                    <button className="button ghost compact" onClick={() => setConfirmingDelete(false)}>
                      取消
                    </button>
                  </div>
                )}
              </section>
            )}
          </>
        )}

        {error && <p className="error-banner share-error">{error}</p>}
      </div>
    </Modal>
  );
}
