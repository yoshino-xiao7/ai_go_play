import { useEffect, useState } from "react";
import { LoaderCircle, Power } from "lucide-react";
import { api, ApiError } from "./api";
import { Modal } from "./ui";
import "./exit-application.css";

type ShutdownStatus = {
  supported: boolean;
  busy: Record<string, number>;
  comfy: { managed: boolean; status: string };
};

export default function ExitApplication({ beforeExit, className = "canvas-small-button" }: {
  beforeExit?: () => Promise<void>;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<ShutdownStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stopComfy, setStopComfy] = useState(true);
  const [accepted, setAccepted] = useState(false);
  const [closed, setClosed] = useState(false);

  useEffect(() => {
    if (!open || accepted || busy) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await api<ShutdownStatus>("/api/system/shutdown");
        if (!cancelled) setStatus(next);
      } catch (e) {
        if (!cancelled) {
          setStatus(null);
          setError(e instanceof ApiError && e.status === 404
            ? "当前运行的是旧版服务。请在任务结束后关闭旧服务，再双击 start.cmd，启用网页退出功能。"
            : e instanceof Error ? e.message : String(e));
        }
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [open, accepted, busy]);

  useEffect(() => {
    if (!accepted || closed) return;
    let cancelled = false;
    const controller = new AbortController();
    const check = async () => {
      try {
        await fetch("/api/health", { cache: "no-store", signal: controller.signal });
      } catch {
        if (!cancelled) setClosed(true);
      }
    };
    const timer = window.setInterval(() => void check(), 1000);
    return () => { cancelled = true; controller.abort(); window.clearInterval(timer); };
  }, [accepted, closed]);

  const exit = async () => {
    setBusy(true);
    setError("");
    try {
      await beforeExit?.();
      await api("/api/system/shutdown", { method: "POST", body: JSON.stringify({ confirm: true, stop_comfy: stopComfy }) });
      setAccepted(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const active = status ? Object.entries(status.busy) : [];
  return <>
    <button type="button" className={`${className} exit-application-trigger`} title="保存并退出整个程序" aria-haspopup="dialog"
      onClick={() => { setError(""); setStatus(null); setOpen(true); }}>
      <Power size={16} /><span>退出程序</span>
    </button>
    {open && <Modal title={accepted ? closed ? "本机服务已关闭" : "正在关闭本机服务" : "退出程序"}
      onClose={() => { if (!busy && !accepted) setOpen(false); }} className={`exit-application-dialog ${accepted ? "exit-application-finished" : ""}`}>
      {accepted ? <div className="modal-body exit-application-result" role="status">
        {closed ? <Power size={32} /> : <LoaderCircle size={32} className="spin" />}
        <p>{closed ? "现在可以关闭此页面。" : "画布已保存，正在清理后台服务，请稍候。"}</p>
        <p className="muted">下次双击项目根目录的 start.cmd，即可继续创作。</p>
      </div> : <div className="modal-body">
        <p>退出前会保存当前画布，然后关闭本机工作台服务。其他已打开的工作台页面也会断开连接。</p>
        <p className="muted">请先保存其他页面的修改。账号和已有项目会保留。</p>
        {status?.comfy.managed && <label className="exit-application-option">
          <input type="checkbox" checked={stopComfy} disabled={busy} onChange={e => setStopComfy(e.target.checked)} />
          同时关闭工作台启动的 ComfyUI，释放显存
        </label>}
        {status && !status.comfy.managed && status.comfy.status === "external" && <p className="muted">另外启动的 ComfyUI 会继续运行，可在它自己的窗口中关闭。</p>}
        {!!active.length && <div className="exit-application-warning" role="status">
          <strong>请先完成或在任务面板中取消这些任务</strong>
          <ul>{active.map(([name, count]) => <li key={name}>{name}：{count}</li>)}</ul>
        </div>}
        {status && !status.supported && <p role="alert">当前服务未通过支持退出的启动器运行，请用 start.cmd 重新启动一次。</p>}
        {error && <p className="exit-application-error" role="alert">{error}</p>}
        <div className="exit-application-actions">
          <button className="button secondary" disabled={busy} onClick={() => setOpen(false)}>继续创作</button>
          <button className="button primary" disabled={busy || !status?.supported || !!active.length} onClick={() => void exit()}>
            {busy && <LoaderCircle size={16} className="spin" />}{busy ? "正在保存并退出…" : "保存并退出程序"}
          </button>
        </div>
      </div>}
    </Modal>}
  </>;
}
