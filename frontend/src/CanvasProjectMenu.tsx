import { useEffect, useMemo, useRef, useState } from "react";
import type { Node } from "@xyflow/react";
import { Check, ChevronDown, Copy, ExternalLink, FolderOpen, Info, Loader2, Pencil, Plus, Search } from "lucide-react";
import { api, mediaUrl } from "./api";
import type { Project } from "./types";
import { Modal } from "./ui";
import { useLayer } from "./shell/layers";
import { copyText } from "./shell/clipboard";

const recentKey = "manju:recent-projects";
function recentProjects(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(recentKey) || "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string").slice(0, 30) : [];
  } catch { return []; }
}
const projectHref = (id: string) => `#/canvas/${encodeURIComponent(id)}`;
const dateText = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

type Props = {
  project: Project;
  nodes: Node[];
  edgeCount: number;
  revision: number;
  onProjectChange: (project: Project) => void;
  onNavigate: (id: string) => Promise<void>;
  onNotice: (message: string) => void;
};

export default function CanvasProjectMenu({ project, nodes, edgeCount, revision, onProjectChange, onNavigate, onNotice }: Props) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [recents, setRecents] = useState<string[]>(recentProjects);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [info, setInfo] = useState(false);
  const [metadata, setMetadata] = useState(project);
  const [editing, setEditing] = useState<Project | "new" | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState("");
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    const ids = [project.id, ...recentProjects().filter(id => id !== project.id)].slice(0, 30);
    setRecents(ids);
    try { localStorage.setItem(recentKey, JSON.stringify(ids)); } catch { /* The switcher also works without browser storage. */ }
  }, [project.id]);

  useEffect(() => () => clearTimeout(copyTimer.current), []);
  // the layer is the dropdown itself (not the wrapper that also holds the trigger), so the trigger
  // stays the opener that Esc / an outside click returns focus to
  useLayer(open, () => setOpen(false), { ref: dropdownRef, outside: true, fallback: () => trigger.current, ignore: target => !!trigger.current?.contains(target) });
  const backToTrigger = () => trigger.current;

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setListError("");
    api<Project[]>("/api/projects").then(value => { if (active) setProjects(value); })
      .catch(error => { if (active) setListError(errorText(error)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, refresh]);

  useEffect(() => {
    if (!info) return;
    let active = true;
    setMetadata(project);
    api<Project>(`/api/projects/${encodeURIComponent(project.id)}`)
      .then(value => { if (active) setMetadata(value); })
      .catch(error => { if (active) onNotice(errorText(error)); });
    return () => { active = false; };
  }, [info, project, revision, onNotice]);

  // Refresh names and available projects when another window or the CLI changes them.
  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      const payload = detail.data || detail.payload || detail;
      if (!String(detail.type || detail.event || payload.type || "").startsWith("project.")) return;
      setRefresh(value => value + 1);
      if (payload.project_id === project.id) {
        api<Project>(`/api/projects/${encodeURIComponent(project.id)}`)
          .then(onProjectChange).catch(error => onNotice(errorText(error)));
      }
    };
    window.addEventListener("manju:event", update);
    return () => window.removeEventListener("manju:event", update);
  }, [project.id, onProjectChange, onNotice]);

  const ordered = useMemo(() => {
    const items = projects.map(item => item.id === project.id ? project : item);
    if (!items.some(item => item.id === project.id)) items.unshift(project);
    const rank = (id: string) => { const index = recents.indexOf(id); return index < 0 ? Number.MAX_SAFE_INTEGER : index; };
    return items.sort((a, b) => rank(a.id) - rank(b.id) || b.updated_at.localeCompare(a.updated_at))
      .filter(item => `${item.name} ${item.id}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  }, [projects, project, recents, search]);

  const stats = useMemo(() => {
    const counts = { image: 0, video: 0, audio: 0, text: 0, subject: 0, frame: 0, group: 0, other: 0 };
    for (const node of nodes) {
      if (node.type === "subject" || node.type === "text" || node.type === "frame" || node.type === "group") counts[node.type]++;
      else if (node.data.kind === "image" || node.data.kind === "video" || node.data.kind === "audio") counts[node.data.kind]++;
      else counts.other++;
    }
    return counts;
  }, [nodes]);

  function startEdit(item: Project | "new") {
    setName(item === "new" ? "未命名项目" : item.name);
    setEditing(item); setEditError(""); setOpen(false);
  }
  async function navigate(id: string) {
    if (busy) return;
    setBusy(true);
    try { await onNavigate(id); setOpen(false); }
    catch (error) { onNotice(errorText(error)); }
    finally { setBusy(false); }
  }
  async function submitName() {
    if (!editing || busy) return;
    const trimmed = name.trim();
    if (!trimmed) { setEditError("项目名称不能为空。"); return; }
    setBusy(true); setEditError("");
    try {
      if (editing !== "new" && trimmed === editing.name) { setEditing(null); return; }
      const saved = await api<Project>(editing === "new" ? "/api/projects" : `/api/projects/${encodeURIComponent(editing.id)}`, {
        method: editing === "new" ? "POST" : "PATCH", body: JSON.stringify({ name: trimmed }),
      });
      setProjects(items => [saved, ...items.filter(item => item.id !== saved.id)]);
      if (saved.id === project.id) onProjectChange(saved);
      setEditing(null);
      if (editing === "new") await onNavigate(saved.id);
      else onNotice("项目已更名。");
    } catch (error) {
      if (editing === "new") onNotice(errorText(error));
      setEditError(errorText(error));
    } finally { setBusy(false); }
  }
  async function copyId() {
    const ok = await copyText(project.id);
    clearTimeout(copyTimer.current);
    if (ok) {
      setCopied(true); setCopyFailed(false);
      onNotice(`已复制画布 ID：${project.id}`);
      copyTimer.current = setTimeout(() => setCopied(false), 2200);
    } else {
      // never fail silently: show the ID selected in the project sheet so Ctrl+C finishes the job
      setCopyFailed(true); setInfo(true);
      onNotice("浏览器拒绝了自动复制，已在项目信息中选中画布 ID，按 Ctrl+C 即可复制。");
    }
  }

  return <>
    <div className="canvas-project-menu" ref={root}>
      <button className="canvas-project-trigger" ref={trigger} aria-label={`切换项目：${project.name}`} aria-expanded={open} aria-controls="canvas-project-switcher" onClick={() => { setOpen(value => !value); setSearch(""); }}>
        <span title={project.name}>{project.name}</span><ChevronDown size={14} />
      </button>
      {open && <div ref={dropdownRef} id="canvas-project-switcher" className="canvas-project-dropdown" aria-label="项目切换">
        <div className="canvas-project-menu-heading"><span>项目</span><button title="当前项目信息" aria-label="当前项目信息" onClick={() => { setInfo(true); setOpen(false); }}><Info size={15} /></button></div>
        <label className="canvas-project-search"><Search size={14} /><input autoFocus aria-label="搜索项目名称或 ID" placeholder="搜索项目名称或 ID" value={search} onChange={event => setSearch(event.target.value)} /></label>
        <div className="canvas-project-list" aria-busy={loading}>
          <p className="canvas-project-section-label">{search ? "搜索结果" : "最近访问 · 其余按修改时间排列"}</p>
          {loading && <p className="canvas-project-list-message"><Loader2 size={14} className="spin" />读取项目中…</p>}
          {listError && <div className="canvas-project-list-message" role="alert">{listError}<button onClick={() => setRefresh(value => value + 1)}>重试</button></div>}
          {!loading && ordered.map(item => <div className={`canvas-project-row ${item.id === project.id ? "current" : ""}`} key={item.id}>
            <button className="canvas-project-open" title={item.name} disabled={busy} aria-current={item.id === project.id ? "page" : undefined} onClick={() => item.id === project.id ? setOpen(false) : void navigate(item.id)}>
              <span className="canvas-project-cover">{item.cover_version_id ? <img src={mediaUrl(item.cover_version_id)} alt="" /> : <FolderOpen size={17} />}</span>
              <span>{item.name}</span>{item.id === project.id && <Check size={14} />}
            </button>
            <button className="canvas-project-row-action" aria-label={`更名项目 ${item.name}`} title="更名项目" disabled={busy} onClick={() => startEdit(item)}><Pencil size={13} /></button>
            <a className="canvas-project-row-action" href={projectHref(item.id)} target="_blank" rel="noopener noreferrer" aria-label={`在新页面打开 ${item.name}`} title="在新页面打开"><ExternalLink size={13} /></a>
          </div>)}
          {!loading && !ordered.length && <p className="canvas-project-list-message">没有匹配的项目</p>}
        </div>
        <div className="canvas-project-menu-footer">
          <button disabled={busy} onClick={() => startEdit("new")}><Plus size={15} />新建项目</button>
          <button onClick={() => { setOpen(false); setInfo(true); }}><Info size={15} />项目信息</button>
        </div>
      </div>}
    </div>
    <button className="canvas-icon-button canvas-project-rename" title="更名当前项目" aria-label="更名当前项目" onClick={() => startEdit(project)}><Pencil size={14} /></button>
    <button className={`canvas-id-chip${copied ? " is-copied" : ""}`} title={`复制画布 ID（供 Agent / CLI 定位此画布）：${project.id}`} aria-label={copied ? "画布 ID 已复制" : `复制画布 ID ${project.id}`} onClick={() => void copyId()}>
      <span className="canvas-id-label">ID</span><code>{project.id.length > 12 ? `${project.id.slice(0, 8)}…${project.id.slice(-4)}` : project.id}</code>
      <span className="canvas-id-icon" aria-hidden="true">{copied ? <Check size={13} /> : <Copy size={13} />}</span>
      <span className="canvas-id-done" aria-live="polite">{copied ? "已复制" : ""}</span>
    </button>

    {editing && <Modal title={editing === "new" ? "新建项目" : "更名项目"} onClose={() => { if (!busy) setEditing(null); }} className="canvas-project-edit-dialog" returnTo={backToTrigger}>
      <form onSubmit={event => { event.preventDefault(); void submitName(); }}>
        <div className="modal-body"><label className="canvas-project-name-field">项目名称<input aria-label="项目名称" value={name} maxLength={250} disabled={busy} onChange={event => setName(event.target.value)} /></label>{editError && <p className="canvas-project-form-error" role="alert">{editError}</p>}</div>
        <footer className="modal-footer"><button type="button" className="button secondary" disabled={busy} onClick={() => setEditing(null)}>取消</button><button className="button primary" disabled={busy || !name.trim()}>{busy ? "处理中…" : editing === "new" ? "创建并打开" : "保存名称"}</button></footer>
      </form>
    </Modal>}

    {info && <Modal title="项目信息" onClose={() => { setInfo(false); setCopyFailed(false); }} wide className="canvas-project-info-dialog" returnTo={backToTrigger}>
      <div className="modal-body">
        <div className="canvas-project-info-title"><h3>{project.name}</h3><button className="button secondary" onClick={() => { setInfo(false); startEdit(project); }}><Pencil size={14} />更名</button><a className="button secondary" href={projectHref(project.id)} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} />新页面打开</a></div>
        <div className="canvas-project-info-id"><span>画布 ID</span><code ref={element => { if (element && copyFailed) { const range = document.createRange(); range.selectNodeContents(element); const selection = getSelection(); selection?.removeAllRanges(); selection?.addRange(range); } }}>{project.id}</code><button className="button secondary" data-autofocus onClick={() => void copyId()}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "已复制" : "复制 ID"}</button></div>
        <p className="canvas-project-info-hint">把画布 ID 交给 Agent 或 CLI，即可定位到这张画布协同创作。顶栏项目名旁的「ID」也能一键复制。</p>
        <dl className="canvas-project-metadata"><div><dt>创建时间</dt><dd>{dateText(metadata.created_at)}</dd></div><div><dt>最近修改</dt><dd>{dateText(metadata.updated_at)}</dd></div><div><dt>画布修订</dt><dd>v{revision}</dd></div><div><dt>画幅</dt><dd>{project.aspect_ratio === "free" ? "自由画布" : project.aspect_ratio}</dd></div></dl>
        <h4>节点分布 <span>当前画布</span></h4>
        <div className="canvas-project-stats">{([
          ["全部节点", nodes.length], ["图片", stats.image], ["视频", stats.video], ["音频", stats.audio], ["文本", stats.text], ["主体", stats.subject], ["画框", stats.frame], ["分组", stats.group], ["其他", stats.other], ["连线", edgeCount],
        ] as const).map(([label, count]) => <div key={label}><span>{label}</span><strong>{count}</strong></div>)}</div>
        <p className="canvas-project-info-hint">平移、缩放、选中与预览仅改变本机视图；编辑内容才会保存并更新修订。</p>
      </div>
    </Modal>}
  </>;
}
