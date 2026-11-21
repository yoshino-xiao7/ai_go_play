import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Edge, Node } from "@xyflow/react";
import { AlertCircle, Check, Copy, LayoutGrid, LoaderCircle, Plus, RefreshCw, Search } from "lucide-react";
import { ApiError, api, dateText, mediaUrl } from "./api";
import type { CanvasData, Project } from "./types";
import { Modal } from "./ui";

type Snapshot = { nodes: Node[]; edges: Edge[] };
type CanvasWrite = CanvasData & { request_id: string };
type Transfer = { project: Project; snapshot: Snapshot; requestId: string; payload?: CanvasWrite };
type Props = {
  sourceProjectId: string;
  snapshot: Snapshot;
  onClose: () => void;
  onSaved: (project: Project) => void;
};
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const messageOf = (error: unknown) => error instanceof Error ? error.message : String(error);

function parentFirst(nodes: Node[]): Node[] {
  const children = new Map<string, Node[]>();
  const queue: Node[] = [];
  for (const node of nodes) {
    if (node.parentId) {
      const siblings = children.get(node.parentId) || [];
      siblings.push(node);
      children.set(node.parentId, siblings);
    }
    else queue.push(node);
  }
  const ordered: Node[] = [];
  for (let index = 0; index < queue.length; index++) {
    const node = queue[index];
    ordered.push(node);
    queue.push(...(children.get(node.id) || []));
  }
  if (ordered.length !== nodes.length) throw new Error("所选分组包含无效的父子关系，请重新选择后再保存。");
  return ordered;
}

/** Clone a selection across projects without inheriting live generation jobs. */
export function cloneCanvasSelection(snapshot: Snapshot): Snapshot {
  const nodeIds = new Map(snapshot.nodes.map(node => [node.id, crypto.randomUUID()]));
  if (!snapshot.nodes.length) throw new Error("请先选择要保存的内容。");
  if (nodeIds.size !== snapshot.nodes.length) throw new Error("所选内容包含重复节点，请重新选择。");
  const internalEdges = snapshot.edges.filter(edge => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const edgeIds = new Map(internalEdges.map(edge => [edge.id, crypto.randomUUID()]));
  if (edgeIds.size !== internalEdges.length) throw new Error("所选内容包含重复连线，请重新选择。");
  const nodes = snapshot.nodes.map(node => {
    const cloned = copy(node);
    cloned.id = nodeIds.get(node.id)!;
    cloned.selected = false;
    delete cloned.dragging;
    delete cloned.measured;
    delete cloned.resizing;
    if (node.parentId && nodeIds.has(node.parentId)) cloned.parentId = nodeIds.get(node.parentId);
    else {
      delete cloned.parentId;
      delete cloned.extent;
      delete cloned.expandParent;
    }
    delete cloned.data.generation_id;
    if (isRecord(cloned.data.shot)) {
      for (const key of ["video_node_id", "audio_node_id"]) {
        const original = cloned.data.shot[key];
        if (typeof original === "string" && nodeIds.has(original)) cloned.data.shot[key] = nodeIds.get(original);
        else delete cloned.data.shot[key];
      }
    }
    // Settings belong to the destination production; a restored snapshot stays a normal frame.
    delete cloned.data.production_settings;
    delete cloned.data.timeline;
    delete cloned.data.production_render_id;
    if (Array.isArray(cloned.data.image_history)) {
      cloned.data.image_history = cloned.data.image_history.map(entry => {
        if (!isRecord(entry)) return entry;
        const history = { ...entry };
        delete history.job_id;
        return history;
      });
    }
    if (isRecord(cloned.data.generation)) {
      const draft = cloned.data.generation;
      for (const key of Object.keys(draft)) if (key === "last_job_id" || key.startsWith("pending")) delete draft[key];
      if (Array.isArray(draft.references)) draft.references = draft.references.map(reference => {
        if (!isRecord(reference)) return reference;
        const next = { ...reference };
        const nodeId = typeof reference.node_id === "string" ? nodeIds.get(reference.node_id) : undefined;
        const edgeId = typeof reference.edge_id === "string" ? edgeIds.get(reference.edge_id) : undefined;
        if (nodeId) next.node_id = nodeId;
        else delete next.node_id;
        if (edgeId) next.edge_id = edgeId;
        else delete next.edge_id;
        if (next.source === "connection" && !edgeId) next.source = "mention";
        if (next.source === "base" && !nodeId) next.source = "mention";
        return next;
      });
      for (const key of ["excluded_edge_ids", "excluded_edges"]) {
        if (Array.isArray(draft[key])) draft[key] = draft[key].flatMap(id => typeof id === "string" && edgeIds.has(id) ? [edgeIds.get(id)!] : []);
      }
    }
    return cloned;
  });
  const edges = internalEdges.map(edge => {
    const cloned = copy(edge);
    cloned.id = edgeIds.get(edge.id)!;
    cloned.source = nodeIds.get(edge.source)!;
    cloned.target = nodeIds.get(edge.target)!;
    cloned.selected = false;
    if (cloned.data) delete cloned.data.generation_id;
    return cloned;
  });
  return { nodes: parentFirst(nodes), edges };
}

function bounds(nodes: Node[]) {
  const byId = new Map(nodes.map(node => [node.id, node]));
  let left = Infinity, top = Infinity, right = -Infinity;
  for (const node of nodes) {
    let x = node.position.x, y = node.position.y, parentId = node.parentId;
    const visited = new Set([node.id]);
    while (parentId && byId.has(parentId) && !visited.has(parentId)) {
      visited.add(parentId);
      const parent = byId.get(parentId)!;
      x += parent.position.x;
      y += parent.position.y;
      parentId = parent.parentId;
    }
    const rawWidth = node.width ?? node.style?.width ?? node.measured?.width ?? 260;
    const parsed = typeof rawWidth === "number" ? rawWidth : Number.parseFloat(String(rawWidth));
    const width = Number.isFinite(parsed) && parsed > 0 ? parsed : 260;
    left = Math.min(left, x);
    top = Math.min(top, y);
    right = Math.max(right, x + width);
  }
  return { left, top, right };
}

/** Preserve target content and viewport; move only copied roots. */
export function mergeCanvasSelection(target: CanvasData, selection: Snapshot, requestId: string): CanvasWrite {
  const targetIds = new Set(target.nodes.map(node => node.id));
  const targetEdges = new Set(target.edges.map(edge => edge.id));
  if (selection.nodes.some(node => targetIds.has(node.id)) || selection.edges.some(edge => targetEdges.has(edge.id))) {
    throw new Error("部分复制内容已经存在，请先打开目标画布确认，避免覆盖后续修改。");
  }
  const sourceBounds = bounds(selection.nodes);
  const targetBounds = bounds(target.nodes);
  const x = target.nodes.length ? targetBounds.right + 80 : 80;
  const y = target.nodes.length ? targetBounds.top : 80;
  const nodes = selection.nodes.map(node => ({
    ...copy(node),
    position: node.parentId ? { ...node.position } : { x: node.position.x + x - sourceBounds.left, y: node.position.y + y - sourceBounds.top },
  }));
  return {
    revision: target.revision,
    nodes: [...target.nodes, ...nodes],
    edges: [...target.edges, ...copy(selection.edges)],
    viewport: { ...target.viewport },
    request_id: requestId,
  };
}

export default function SaveToCanvasDialog({ sourceProjectId, snapshot, onClose, onSaved }: Props) {
  const [selection] = useState(() => copy(snapshot));
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState("");
  const [creationUncertain, setCreationUncertain] = useState(false);
  const busyRef = useRef(false);
  const mounted = useRef(true);
  const sequence = useRef(0);
  const transfers = useRef(new Map<string, Transfer>());
  const nameInput = useRef<HTMLInputElement>(null);

  const loadProjects = async () => {
    const request = ++sequence.current;
    setLoading(true);
    try {
      const result = await api<Project[]>("/api/projects?trash=false");
      if (mounted.current && request === sequence.current) {
        setProjects(result.filter(project => project.id !== sourceProjectId && !project.deleted_at));
        setLoadError("");
      }
    } catch (caught) {
      if (mounted.current && request === sequence.current) setLoadError(messageOf(caught));
    } finally {
      if (mounted.current && request === sequence.current) setLoading(false);
    }
  };
  useEffect(() => {
    mounted.current = true;
    void loadProjects();
    return () => { mounted.current = false; sequence.current++; };
    // This dialog owns one frozen source selection for its entire lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceProjectId]);
  useEffect(() => { if (creating) nameInput.current?.focus(); }, [creating]);

  const close = () => { if (!busyRef.current) onClose(); };
  const chooseProject = (project: Project) => {
    if (busyRef.current) return;
    setSelectedId(project.id);
    setCreating(false);
    setError("");
  };
  const save = async () => {
    if (busyRef.current || !selection.nodes.length || creating && (!name.trim() || creationUncertain) || !creating && !selectedId) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      let project: Project;
      if (creating) {
        setPhase("正在新建画布…");
        try {
          project = await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name: name.trim(), aspect_ratio: "free" }) });
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status >= 500) {
            setCreationUncertain(true);
            setCreating(false);
            setSelectedId("");
            void loadProjects();
            throw new Error("新建画布的结果尚未确认。请刷新列表，选择已创建的画布继续保存，避免重复新建。");
          }
          throw caught;
        }
        setProjects(current => [project, ...current.filter(item => item.id !== project.id)]);
        setSelectedId(project.id);
        setCreating(false);
      } else project = await api<Project>(`/api/projects/${selectedId}`);
      if (project.id === sourceProjectId || project.deleted_at) throw new Error("目标画布不可用，请重新选择。");
      let transfer = transfers.current.get(project.id);
      if (!transfer) {
        transfer = { project, snapshot: cloneCanvasSelection(selection), requestId: `save-to-canvas:${crypto.randomUUID()}` };
        transfers.current.set(project.id, transfer);
      } else transfer.project = project;
      const path = `/api/projects/${project.id}/canvas`;
      let completed: CanvasData | undefined;
      for (let conflicts = 0; conflicts <= 2; conflicts++) {
        setPhase(conflicts ? "目标画布有更新，正在合并…" : "正在保存所选内容…");
        // A connection failure may follow a committed write. Re-send its exact
        // payload first, so the server can return the idempotency receipt.
        if (!transfer.payload) {
          const target = await api<CanvasData>(path);
          const nodeIds = new Set(target.nodes.map(node => node.id));
          const edgeIds = new Set(target.edges.map(edge => edge.id));
          if (transfer.snapshot.nodes.every(node => nodeIds.has(node.id)) && transfer.snapshot.edges.every(edge => edgeIds.has(edge.id))) {
            completed = target;
            break;
          }
          transfer.payload = mergeCanvasSelection(target, transfer.snapshot, transfer.requestId);
        }
        try {
          completed = await api<CanvasData>(path, { method: "PUT", body: JSON.stringify(transfer.payload) });
          break;
        } catch (caught) {
          const detail = caught instanceof ApiError && isRecord(caught.detail) ? caught.detail : {};
          if (caught instanceof ApiError && caught.status === 409 && detail.code === "revision_conflict") {
            transfer.payload = undefined;
            if (conflicts < 2) continue;
            throw new Error("目标画布正在频繁更新。本次未覆盖其他修改，请稍后重试。");
          }
          // Definitive rejected writes can be rebuilt on a later attempt.
          if (caught instanceof ApiError && caught.status < 500) transfer.payload = undefined;
          throw caught;
        }
      }
      if (!completed) throw new Error("保存未完成，请重试。");
      const saved = await api<Project>(`/api/projects/${project.id}`).catch(() => ({ ...project, revision: completed!.revision }));
      if (mounted.current) onSaved(saved);
    } catch (caught) {
      if (mounted.current) {
        const uncertainWrite = [...transfers.current.values()].some(transfer => transfer.payload) && (!(caught instanceof ApiError) || caught.status >= 500);
        setError(uncertainWrite ? `${messageOf(caught)}。保存结果暂未确认，重试会核验同一次保存。` : messageOf(caught));
      }
    } finally {
      busyRef.current = false;
      if (mounted.current) { setBusy(false); setPhase(""); }
    }
  };
  const filtered = projects.filter(project => project.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const selectedProject = projects.find(project => project.id === selectedId);
  const canSave = !busy && selection.nodes.length > 0 && (creating ? !!name.trim() && !creationUncertain : !!selectedProject);

  return createPortal(<Modal title="保存到其他画布" onClose={close}>
    <div className="save-canvas-dialog">
      <p className="save-canvas-summary"><Copy size={16} /><span>复制所选 {selection.nodes.length} 个元素及内部连线，源画布保留。</span></p>
      <label className="save-canvas-search"><Search size={16} /><input autoFocus aria-label="搜索目标画布" placeholder="搜索画布名称" value={query} disabled={busy} onChange={event => setQuery(event.target.value)} /></label>
      <button className={`save-canvas-create ${creating ? "selected" : ""}`} disabled={busy || creationUncertain} aria-pressed={creating} onClick={() => { setCreating(true); setSelectedId(""); setName(current => current || query.trim()); setError(""); }}><span className="save-canvas-new-icon"><Plus size={19} /></span><span><strong>新建画布</strong><small>将所选内容保存到新的自由画布</small></span>{creating && <Check size={17} />}</button>
      {creating && <label className="save-canvas-name">画布名称<input ref={nameInput} aria-label="新画布名称" value={name} maxLength={250} placeholder="输入新画布的名称" disabled={busy} onChange={event => setName(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.nativeEvent.isComposing) void save(); }} /></label>}
      <div className="save-canvas-list-heading"><span>已有画布</span><button type="button" title="刷新画布列表" disabled={busy || loading} onClick={() => void loadProjects()}><RefreshCw size={13} /></button></div>
      <div className="save-canvas-projects" role="listbox" aria-label="目标画布" onKeyDown={event => {
        if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
        const options = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="option"]:not(:disabled)'));
        if (!options.length) return;
        const index = options.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : event.key === "ArrowDown" ? Math.min(options.length - 1, index + 1) : Math.max(0, index - 1);
        event.preventDefault();
        options[next].focus();
      }}>
        {loading ? <div className="save-canvas-empty"><LoaderCircle size={18} className="spin" />正在读取画布</div> : loadError ? <div className="save-canvas-empty error"><AlertCircle size={18} /><span>{loadError}</span><button onClick={() => void loadProjects()}>重新读取</button></div> : !filtered.length ? <div className="save-canvas-empty"><LayoutGrid size={21} /><span>{query.trim() ? "没有匹配的画布，可以新建一个。" : "还没有其他画布，可以在上方新建。"}</span></div> : filtered.map(project => <button key={project.id} type="button" role="option" aria-selected={!creating && selectedId === project.id} className={`save-canvas-project ${!creating && selectedId === project.id ? "selected" : ""}`} disabled={busy} onClick={() => chooseProject(project)}><span className="save-canvas-cover">{project.cover_version_id ? <img src={mediaUrl(project.cover_version_id)} alt="" /> : <LayoutGrid size={19} />}</span><span className="save-canvas-project-copy"><strong>{project.name}</strong><small>{project.aspect_ratio === "free" ? "自由画布" : project.aspect_ratio} · 更新于 {dateText(project.updated_at)}</small></span>{!creating && selectedId === project.id && <Check size={17} />}</button>)}
      </div>
      {error && <div className="save-canvas-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
      {creationUncertain && <div className="save-canvas-recover"><span>刷新列表确认结果；如果没有创建成功，可以重新新建。</span><button disabled={busy || loading} onClick={() => { setCreationUncertain(false); setCreating(true); setSelectedId(""); setError(""); }}>确认未创建，重新新建</button></div>}
      <p className="save-canvas-note">图片、视频和音频继续使用原素材版本，无需重复存储。</p>
    </div>
    <footer className="modal-footer save-canvas-footer"><span>{busy ? phase : creating ? "保存后会创建新画布" : selectedProject ? `保存至「${selectedProject.name}」` : "选择一个目标画布"}</span><button className="button secondary" disabled={busy} onClick={close}>取消</button><button className="button primary" disabled={!canSave} onClick={() => void save()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Copy size={15} />}{busy ? "保存中" : "保存到画布"}</button></footer>
  </Modal>, document.body);
}
