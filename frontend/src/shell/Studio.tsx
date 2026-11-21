import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  AlertCircle, ArchiveRestore, ArrowDownToLine, BookOpen, Check, Cloud, CircuitBoard, ExternalLink, FolderKanban, GitBranch,
  Images, Info, LoaderCircle, LogOut, MoreHorizontal, RefreshCw, Search, Settings2, Share2, Sparkles, Spline,
  User, UsersRound, X, Film,
} from "lucide-react";
import Ambience from "./Ambience";
import BootIris from "./BootIris";
import CommandPalette, { useCommandPaletteHotkey } from "./CommandPalette";
import { installFx, withViewTransition } from "./fx";
import { api, uploadAsset } from "../api";
import type { Project, SetuUser, ShareStatus } from "../types";
import { EmptyState, Loading, Modal } from "../ui";
import ExitApplication from "../ExitApplication";
import { AssetInspector, Library, Projects, StorageSettings, Trash } from "../Pages";
import EnginePill from "./EnginePill";
import Tray from "./Tray";
import { flushOpenCanvas, forgetProject, lastProject, rememberProject, sendCanvasCommand } from "./canvasBridge";
import { ShellSlotsContext } from "./slots";

const Canvas = lazy(() => import("../Canvas"));
const ComfyPanel = lazy(() => import("../ComfyPanel"));
const Workflows = lazy(() => import("../Workflows"));
const About = lazy(() => import("../About"));

type Notify = (message: string, error?: boolean) => void;
type UploadItem = { id: string; file: File; progress: number; status: "uploading" | "done" | "failed"; error?: string };
export type CanvasView = "canvas" | "guide" | "script" | "subjects" | "timeline";

function useRoute() {
  const [route, setRoute] = useState(location.hash.slice(1) || "/projects");
  useEffect(() => {
    // Every route change plays as a View Transition (stage morphs; the dock glider springs on its own).
    const change = () => {
      const next = location.hash.slice(1) || "/projects";
      withViewTransition(() => flushSync(() => setRoute(next)));
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  return route;
}
const go = (target: string) => { window.location.hash = target; };

const sectionTitles: Record<string, string> = {
  projects: "项目", assets: "素材库", workflows: "工作流", settings: "设置", trash: "回收站", about: "关于",
  canvas: "画布", guide: "画布 · 新手引导", script: "剧本", subjects: "主体", timeline: "时间线",
};

/** The studio shell: rail, top bar, view stage and the 显影槽 tray. Views keep their own data logic. */
export default function Studio() {
  const route = useRoute();
  const [refresh, setRefresh] = useState(0);
  const [connected, setConnected] = useState(false);
  const [toast, setToast] = useState<{ text: string; error: boolean; key: number } | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [projectError, setProjectError] = useState("");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [comfyOpen, setComfyOpen] = useState(false);
  const [trayOpen, setTrayOpen] = useState(false);
  const [activeJobs, setActiveJobs] = useState(0);
  const [moreOpen, setMoreOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const dockRef = useRef<HTMLElement>(null);
  const gliderRef = useRef<HTMLSpanElement>(null);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useCommandPaletteHotkey(openPalette);
  useEffect(() => installFx(), []);
  // Portal hosts in the top bar: always mounted at the same place (see shell/slots.ts).
  const [projectSlot, setProjectSlot] = useState<HTMLElement | null>(null);
  const [statusSlot, setStatusSlot] = useState<HTMLElement | null>(null);
  const slots = useMemo(() => ({ project: projectSlot, status: statusSlot }), [projectSlot, statusSlot]);
  const notify = useCallback<Notify>((text, error = false) => setToast({ text, error, key: Date.now() }), []);
  const changed = useCallback(() => setRefresh(value => value + 1), []);
  const openComfy = useCallback(() => setComfyOpen(true), []);
  const closeComfy = useCallback(() => setComfyOpen(false), []);

  const parts = route.split("/");
  const projectId = parts[1] === "canvas" ? decodeURIComponent(parts[2] || "") || null : null;
  const canvasView = (projectId ? (["guide", "script", "subjects", "timeline"].includes(parts[3]) ? parts[3] : "canvas") : null) as CanvasView | null;
  const section = projectId ? canvasView! : parts[1] || "projects";
  const remembered = projectId || lastProject();

  // ---------------------------------------------------------------- account (亦可) binding
  const [shareStatus, setShareStatus] = useState<ShareStatus | null>(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [connectingYike, setConnectingYike] = useState<{ requestId: string; url: string } | null>(null);
  const refreshShareStatus = useCallback(async () => {
    try { setShareStatus(await api<ShareStatus>("/api/share/status")); } catch { /* optional account */ }
  }, []);
  useEffect(() => {
    void refreshShareStatus();
    const update = () => void refreshShareStatus();
    window.addEventListener("focus", update);
    window.addEventListener("manju:reconnected", update);
    return () => { window.removeEventListener("focus", update); window.removeEventListener("manju:reconnected", update); };
  }, [refreshShareStatus]);
  useEffect(() => {
    if (!connectingYike) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const result = await api<{ state: "pending" | "approved" | "failed" | "expired"; user?: SetuUser | null; error?: string | null }>(`/api/share/connect/${connectingYike.requestId}`);
        if (cancelled) return;
        if (result.state === "approved") { setConnectingYike(null); await refreshShareStatus(); notify("已成功连接亦可账号！"); }
        else if (result.state !== "pending") { setConnectingYike(null); notify(result.error || "授权已超时，请重新发起连接。", true); }
      } catch (error) {
        if (!cancelled) { setConnectingYike(null); notify(error instanceof Error ? error.message : String(error), true); }
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [connectingYike, notify, refreshShareStatus]);
  const connectYike = async () => {
    setShareBusy(true);
    try {
      const result = await api<{ request_id: string; authorize_url: string }>("/api/share/connect", { method: "POST" });
      setConnectingYike({ requestId: result.request_id, url: result.authorize_url });
      window.open(result.authorize_url, "_blank");
    } catch (error) { notify(error instanceof Error ? error.message : String(error), true); }
    finally { setShareBusy(false); }
  };
  const disconnectYike = async () => {
    setShareBusy(true);
    try { await api("/api/share/disconnect", { method: "POST" }); await refreshShareStatus(); setMoreOpen(false); notify("已解除亦可账号绑定"); }
    catch (error) { notify(error instanceof Error ? error.message : String(error), true); }
    finally { setShareBusy(false); }
  };

  // ---------------------------------------------------------------- service events
  useEffect(() => {
    if (!toast) return;
    const timeout = setTimeout(() => setToast(null), toast.error ? 8500 : 3500);
    return () => clearTimeout(timeout);
  }, [toast]);
  useEffect(() => {
    const source = new EventSource("/api/events");
    source.onopen = () => { setConnected(true); changed(); window.dispatchEvent(new CustomEvent("manju:reconnected")); };
    source.onerror = () => setConnected(false);
    source.onmessage = event => {
      try {
        const payload = JSON.parse(event.data);
        window.dispatchEvent(new CustomEvent("manju:event", { detail: payload }));
        if (payload.type !== "generation.updated") changed();
      } catch { /* keepalive frames */ }
    };
    return () => source.close();
  }, [changed]);
  useEffect(() => {
    if (!projectId) { setProject(null); return; }
    let active = true;
    setProjectError("");
    api<Project>(`/api/projects/${projectId}`)
      .then(value => { if (active) { setProject(value); rememberProject(value.id); } })
      .catch(error => { if (active) { setProjectError(error.message); forgetProject(projectId); } });
    return () => { active = false; };
  }, [projectId]);
  useEffect(() => {
    if (!moreOpen) return;
    const outside = (event: MouseEvent) => { if (!moreRef.current?.contains(event.target as Node)) setMoreOpen(false); };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [moreOpen]);

  // ---------------------------------------------------------------- uploads (素材库)
  const uploadOne = async (item: UploadItem) => {
    setUploads(current => current.map(value => value.id === item.id ? { ...value, status: "uploading", error: undefined, progress: 0 } : value));
    try {
      await uploadAsset(item.file, { onProgress: progress => setUploads(current => current.map(value => value.id === item.id ? { ...value, progress } : value)) });
      setUploads(current => current.map(value => value.id === item.id ? { ...value, status: "done", progress: 100 } : value));
      changed();
    } catch (error) {
      setUploads(current => current.map(value => value.id === item.id ? { ...value, status: "failed", error: (error as Error).message } : value));
    }
  };
  const uploadFiles = async (files: FileList | File[]) => {
    const incoming: UploadItem[] = Array.from(files).map(file => ({ id: crypto.randomUUID(), file, progress: 0, status: "uploading" }));
    setUploads(current => [...current, ...incoming]);
    for (const item of incoming) await uploadOne(item);
  };

  /** Leaving the canvas through the rail saves first; a failed save keeps the user where they are. */
  const navigate = async (target: string) => {
    if (projectId && !target.startsWith(`/canvas/${projectId}`)) {
      try { await flushOpenCanvas(); } catch (error) { notify(error instanceof Error ? error.message : String(error), true); return; }
    }
    go(target);
  };
  const projectRoute = (view = "") => remembered ? `/canvas/${encodeURIComponent(remembered)}${view ? "/" + view : ""}` : "/projects";
  const railItems: { id: string; label: string; icon: React.ReactNode; to: string; needsProject?: boolean }[] = [
    { id: "projects", label: "项目", icon: <FolderKanban size={20} />, to: "/projects" },
    { id: "canvas", label: "画布", icon: <Spline size={20} />, to: projectRoute(), needsProject: true },
    { id: "script", label: "剧本", icon: <BookOpen size={20} />, to: projectRoute("script"), needsProject: true },
    { id: "subjects", label: "主体", icon: <UsersRound size={20} />, to: projectRoute("subjects"), needsProject: true },
    { id: "timeline", label: "时间线", icon: <Film size={20} />, to: projectRoute("timeline"), needsProject: true },
  ];
  const railTools = [
    { id: "assets", label: "素材", icon: <Images size={20} />, to: "/assets" },
    { id: "workflows", label: "工作流", icon: <GitBranch size={20} />, to: "/workflows" },
  ];
  const isActive = (id: string) => id === "canvas" ? section === "canvas" || section === "guide" : section === id;

  // Dock glider: a liquid light pill that springs to the active item.
  useLayoutEffect(() => {
    const place = () => {
      const dock = dockRef.current;
      const glider = gliderRef.current;
      if (!dock || !glider) return;
      const on = dock.querySelector<HTMLElement>(".dock-btn.is-on");
      if (!on) { glider.style.opacity = "0"; return; }
      const prev = Number(glider.dataset.y || on.offsetTop);
      const next = on.offsetTop;
      glider.dataset.y = String(next);
      glider.style.opacity = "1";
      glider.style.setProperty("--y", `${next}px`);
      glider.style.setProperty("--h", `${on.offsetHeight}px`);
      // Stretch while travelling, like a drop of light.
      glider.style.setProperty("--stretch", String(1 + Math.min(0.6, Math.abs(next - prev) / 260)));
      window.setTimeout(() => glider.style.setProperty("--stretch", "1"), 180);
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [section, comfyOpen, moreOpen, remembered]);

  // Dock magnification: items swell as the pointer passes, falling off with distance.
  const magnify = (event: React.PointerEvent<HTMLElement>) => {
    if (event.pointerType === "touch") return;
    for (const btn of event.currentTarget.querySelectorAll<HTMLElement>(".dock-btn")) {
      const box = btn.getBoundingClientRect();
      const distance = Math.abs(event.clientY - (box.top + box.height / 2));
      btn.style.setProperty("--s", (1 + 0.32 * Math.max(0, 1 - distance / 120)).toFixed(3));
    }
  };
  const unmagnify = (event: React.PointerEvent<HTMLElement>) => {
    for (const btn of event.currentTarget.querySelectorAll<HTMLElement>(".dock-btn")) btn.style.removeProperty("--s");
  };
  const newProject = () => {
    try { sessionStorage.setItem("manju:intent", "new-project"); } catch { /* optional */ }
    if (section === "projects") window.dispatchEvent(new CustomEvent("manju:new-project"));
    else void navigate("/projects");
  };

  const view = projectId ? (
    projectError ? (
      <div className="page"><EmptyState icon={<AlertCircle />} title="无法打开项目" description={projectError}
        action={<button className="button secondary" onClick={() => go("/projects")}>返回项目</button>} /></div>
    ) : project?.id === projectId ? (
      <Suspense fallback={<Loading />}>
        <Canvas key={projectId} project={project} view={canvasView!} onBack={() => go("/projects")} onProjectChange={setProject}
          onPreview={setPreviewId} assetsRefresh={refresh} onAssetsChange={changed} onOpenComfy={openComfy}
          onOpenTasks={() => setTrayOpen(true)} onCloseView={() => go(`/canvas/${encodeURIComponent(project.id)}`)} />
      </Suspense>
    ) : <Loading />
  ) : section === "assets" ? <Library refresh={refresh} onChanged={changed} onPreview={setPreviewId} notify={notify} uploadFiles={uploadFiles} />
    : section === "workflows" ? <Suspense fallback={<Loading />}><Workflows refresh={refresh} onChanged={changed} onOpenComfy={openComfy} /></Suspense>
    : section === "about" ? <Suspense fallback={<Loading />}><About notify={notify} /></Suspense>
    : section === "settings" ? <StorageSettings refresh={refresh} onChanged={changed} notify={notify} />
    : section === "trash" ? <Trash refresh={refresh} onChanged={changed} notify={notify} />
    : <Projects refresh={refresh} onChanged={changed} notify={notify} shareSite={shareStatus?.siteBase} />;

  return (
    <div className="studio" data-section={section} data-tray={trayOpen ? "open" : "closed"} data-mode={projectId ? "canvas" : "page"}>
      <Ambience calm={!!projectId} />
      <BootIris />
      <nav className="dock" aria-label="主导航" ref={dockRef} onPointerMove={magnify} onPointerLeave={unmagnify}>
        <a className="dock-logo" href="#/projects" aria-label="ai-go-play 首页" title="ai-go-play · AI to AI 协同创作工作台" data-magnetic="0.3">
          <svg viewBox="0 0 40 40" aria-hidden="true">
            <defs>
              <linearGradient id="dock-logo-g" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0" stopColor="var(--accent-hover)" /><stop offset="0.5" stopColor="var(--accent)" /><stop offset="1" stopColor="var(--accent-deep)" />
              </linearGradient>
            </defs>
            <circle cx="20" cy="20" r="17" fill="none" stroke="url(#dock-logo-g)" strokeWidth="2.2" />
            <circle cx="20" cy="20" r="6" fill="url(#dock-logo-g)" />
            <g className="dock-logo-holes" fill="url(#dock-logo-g)"><circle cx="20" cy="8.5" r="3" /><circle cx="31.5" cy="20" r="3" /><circle cx="20" cy="31.5" r="3" /><circle cx="8.5" cy="20" r="3" /></g>
          </svg>
        </a>
        <span className="dock-glider" ref={gliderRef} aria-hidden="true" />
        <div className="dock-group">
          {railItems.map(item => (
            <button key={item.id} className={`dock-btn ${isActive(item.id) ? "is-on" : ""}`} aria-current={isActive(item.id) ? "page" : undefined}
              disabled={item.needsProject && !remembered} data-label={item.needsProject && !remembered ? `${item.label} · 先打开一个项目` : item.label}
              aria-label={item.label} onClick={() => void navigate(item.to)}>{item.icon}<span>{item.label}</span></button>
          ))}
        </div>
        <span className="dock-div" />
        <div className="dock-group">
          {railTools.map(item => (
            <button key={item.id} className={`dock-btn ${isActive(item.id) ? "is-on" : ""}`} aria-current={isActive(item.id) ? "page" : undefined}
              data-label={item.label} aria-label={item.label} onClick={() => void navigate(item.to)}>{item.icon}<span>{item.label}</span></button>
          ))}
          <button className={`dock-btn ${comfyOpen ? "is-lit" : ""}`} onClick={openComfy} aria-expanded={comfyOpen} data-label="引擎 · ComfyUI" aria-label="引擎"><CircuitBoard size={20} /><span>引擎</span></button>
        </div>
        <div className="dock-spacer" />
        <button className={`dock-btn ${isActive("settings") ? "is-on" : ""}`} data-label="设置" aria-label="设置" onClick={() => void navigate("/settings")}><Settings2 size={20} /><span>设置</span></button>
        <div className="dock-more" ref={moreRef}>
          <button className={`dock-btn ${moreOpen ? "is-lit" : ""}`} aria-expanded={moreOpen} data-label="更多" aria-label="更多" onClick={() => setMoreOpen(value => !value)}><MoreHorizontal size={20} /><span>更多</span></button>
          {moreOpen && (
            <div className="dock-popover" role="menu">
              {shareStatus?.connected && shareStatus.user ? (
                <div className="dock-account">
                  <span className="dock-avatar">{shareStatus.user.avatarUrl ? <img src={shareStatus.user.avatarUrl} alt="" /> : (shareStatus.user.nickname || "YK").slice(0, 1).toUpperCase()}</span>
                  <span><b>{shareStatus.user.nickname || "亦可用户"}</b><small>亦可账号 · UID {shareStatus.user.id}</small></span>
                </div>
              ) : (
                <button role="menuitem" onClick={() => void connectYike()} disabled={shareBusy}><Cloud size={15} />绑定亦可账号<small>一键分享画布</small></button>
              )}
              {shareStatus?.connected && <>
                <button role="menuitem" onClick={() => { window.open(`${shareStatus.siteBase}/canvas`, "_blank"); setMoreOpen(false); }}><Sparkles size={15} />亦可画布广场<ExternalLink size={12} /></button>
                <button role="menuitem" onClick={() => { window.open(`${shareStatus.siteBase}/app/profile`, "_blank"); setMoreOpen(false); }}><User size={15} />个人中心 · 我的分享<ExternalLink size={12} /></button>
                <button role="menuitem" className="is-danger" disabled={shareBusy} onClick={() => void disconnectYike()}><LogOut size={15} />解除绑定</button>
              </>}
              <span className="dock-popover-div" />
              <a role="menuitem" href="#/setup" onClick={() => setMoreOpen(false)}><ArrowDownToLine size={15} />安装向导</a>
              <button role="menuitem" onClick={() => { setMoreOpen(false); void navigate("/trash"); }}><ArchiveRestore size={15} />回收站</button>
              <button role="menuitem" onClick={() => { setMoreOpen(false); void navigate("/about"); }}><Info size={15} />关于</button>
              <span className="dock-popover-div" />
              <ExitApplication className="dock-popover-exit" beforeExit={flushOpenCanvas} />
            </div>
          )}
        </div>
        <span className={`dock-link-state ${connected ? "is-online" : ""}`} role="status" title={connected ? "本机服务已连接" : "正在连接本机服务"}><i />{connected ? "本机" : "重连"}</span>
      </nav>

      <header className="topbar">
        {/* Fixed child list: the two portal hosts keep one DOM node for the life of the shell. */}
        <div className="crumb">
          <span className="crumb-brand"><i>{projectId ? "Reel" : "ai_go_play"}</i></span>
          <span ref={setProjectSlot} className="crumb-slot" hidden={!projectId} />
          <span className="crumb-sep">/</span>
          <span className="crumb-view" key={section}>{sectionTitles[section] || "工作台"}</span>
        </div>
        <div ref={setStatusSlot} className="top-status" />
        <div className="top-right">
          <button className="cmdk-trigger" onClick={openPalette} aria-label="打开命令面板" title="搜索项目、视图或命令">
            <Search size={15} /><span>搜索或执行…</span><kbd>Ctrl K</kbd>
          </button>
          <EnginePill onOpen={openComfy} />
          <button className={`top-tray ${activeJobs ? "is-live" : ""}`} onClick={() => setTrayOpen(value => !value)} aria-expanded={trayOpen}>
            显影槽 <b className="count">{activeJobs}</b>
          </button>
          {projectId && project && (
            <button className="button primary top-share" data-magnetic="0.18" onClick={() => sendCanvasCommand("share")}><Share2 size={15} />导出 / 分享</button>
          )}
        </div>
      </header>

      <main className={`stage ${projectId ? "is-canvas" : "is-page"}`}>
        <ShellSlotsContext.Provider value={slots}>
          <div className="stage-view" key={projectId ? `canvas:${projectId}` : section}>{view}</div>
        </ShellSlotsContext.Provider>
      </main>

      <Tray open={trayOpen} onToggle={setTrayOpen} currentProjectId={projectId} refresh={refresh} notify={notify} onActiveChange={setActiveJobs} />

      {paletteOpen && (
        <CommandPalette onClose={() => setPaletteOpen(false)} navigate={to => void navigate(to)} projectId={projectId}
          openComfy={openComfy} toggleTray={() => setTrayOpen(value => !value)} newProject={newProject} />
      )}
      {comfyOpen && <Suspense fallback={<Modal title="ComfyUI 本地服务" onClose={closeComfy}><Loading /></Modal>}><ComfyPanel onClose={closeComfy} /></Suspense>}
      {previewId && <AssetInspector versionId={previewId} onClose={() => setPreviewId(null)} notify={notify} onChanged={changed} />}
      {toast && (
        <div key={toast.key} className={`toast ${toast.error ? "error" : ""}`} role="status" style={{ "--life": toast.error ? "8.5s" : "3.5s" } as React.CSSProperties}>
          <span className="toast-icon">{toast.error ? <AlertCircle size={16} /> : <Check size={16} />}</span>
          <span>{toast.text}</span>
          <button className="icon-button" onClick={() => setToast(null)} aria-label="关闭消息"><X size={15} /></button>
        </div>
      )}
      {uploads.length > 0 && (
        <aside className="upload-panel" aria-label="导入素材">
          <header>
            <span>导入素材 <small>{uploads.filter(item => item.status === "done").length}/{uploads.length}</small></span>
            <button className="icon-button" title="收起已完成" onClick={() => setUploads(current => current.filter(item => item.status === "uploading"))}><X size={16} /></button>
          </header>
          <div className="upload-list">
            {uploads.map(item => (
              <div className={`upload-item is-${item.status}`} key={item.id}>
                <span className="upload-icon">{item.status === "done" ? <Check size={16} /> : item.status === "failed" ? <AlertCircle size={16} /> : <LoaderCircle className="spin" size={16} />}</span>
                <div className="upload-info">
                  <span>{item.file.name}</span>
                  <small>{item.error || (item.status === "done" ? "已保存到本地素材库" : `${item.progress}%`)}</small>
                  {item.status === "uploading" && <progress value={item.progress} max={100} />}
                </div>
                {item.status === "failed" && <button className="icon-button" title="重试导入" onClick={() => void uploadOne(item)}><RefreshCw size={15} /></button>}
              </div>
            ))}
          </div>
        </aside>
      )}
      {connectingYike && (
        <Modal title="连接亦可账号" onClose={() => setConnectingYike(null)} className="yike-connect-modal">
          <div className="modal-body yike-connect">
            <span className="yike-connect-orb"><Cloud size={28} /><LoaderCircle size={18} className="spin" /></span>
            <h3>正在等待浏览器授权…</h3>
            <p>已在默认浏览器打开亦可授权页面。请登录并点击<strong>「授权连接」</strong>。</p>
          </div>
          <footer className="modal-footer">
            <button className="button secondary" onClick={() => window.open(connectingYike.url, "_blank")}><ExternalLink size={15} />重新打开授权页</button>
            <button className="button secondary" onClick={() => setConnectingYike(null)}>取消</button>
          </footer>
        </Modal>
      )}
    </div>
  );
}
