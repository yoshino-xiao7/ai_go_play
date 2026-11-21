import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

type ComfyState = "not_configured" | "stopped" | "starting" | "running" | "stopping" | "external" | "port_conflict" | "error";
type ComfyStatus = { status: ComfyState; port: number; base_url: string; queue: { running: number; pending: number } | null };

const labels: Record<ComfyState, string> = {
  not_configured: "未配置",
  stopped: "未启动",
  starting: "启动中",
  running: "就绪",
  stopping: "停止中",
  external: "外部服务",
  port_conflict: "端口冲突",
  error: "异常",
};

/** Engine status in the top bar. Opens the ComfyUI manager; never starts or stops the engine itself. */
export default function EnginePill({ onOpen }: { onOpen: () => void }) {
  const [status, setStatus] = useState<ComfyStatus | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const load = useCallback(async () => {
    try {
      setStatus(await api<ComfyStatus>("/api/comfy", { signal: AbortSignal.timeout(7000) }));
      setUnreachable(false);
    } catch { setUnreachable(true); }
  }, []);
  const busy = !!status?.queue && status.queue.running + status.queue.pending > 0;
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), busy ? 4000 : 12000);
    const listener = (event: Event) => {
      const type = String((event as CustomEvent).detail?.type || "");
      if (type.startsWith("comfy") || type.startsWith("generation.")) void load();
    };
    window.addEventListener("manju:event", listener);
    return () => { clearInterval(timer); window.removeEventListener("manju:event", listener); };
  }, [load, busy]);
  const state = unreachable ? "error" : status?.status;
  const tone = !state ? "idle" : state === "running" || state === "external" ? (busy ? "busy" : "ok") : state === "starting" || state === "stopping" ? "busy" : state === "error" || state === "port_conflict" ? "bad" : "off";
  const host = status?.base_url?.replace(/^https?:\/\//, "") || (status ? `127.0.0.1:${status.port}` : "");
  return (
    <button className={`engine-pill tone-${tone}`} onClick={onOpen} title="管理本机 ComfyUI 引擎">
      <span className="orb" aria-hidden="true" />
      <span className="engine-text">
        <b>ComfyUI</b>
        <em>{unreachable ? "服务不可达" : state ? labels[state] : "读取中"}{busy && status?.queue ? ` · 引擎内 ${status.queue.running + status.queue.pending}` : ""}</em>
      </span>
      {host && <small>{host}</small>}
    </button>
  );
}
