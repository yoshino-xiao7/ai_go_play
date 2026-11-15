import { useEffect, useRef, useState } from "react";
import type { Edge, Node } from "@xyflow/react";
import { Download, FolderOpen, Upload } from "lucide-react";
import { Modal } from "./ui";
import { listCanvasDrafts } from "./canvasDraftStore";

export type RecoverableCanvas = { project_id?: string; revision?: number; nodes: Node[]; edges: Edge[]; saved_at?: number };
type Entry = { key: string; name: string; document: RecoverableCanvas };

export function parseCanvasDraft(value: unknown, projectId: string): RecoverableCanvas {
  if (!value || typeof value !== "object") throw new Error("文件不是有效的画布草稿。");
  const draft = value as RecoverableCanvas;
  if (draft.project_id && draft.project_id !== projectId) throw new Error("这份草稿属于其他项目，请在原项目恢复，或使用项目包导入。");
  if (!Array.isArray(draft.nodes) || !Array.isArray(draft.edges) || !draft.nodes.length || draft.nodes.length > 20000 || draft.edges.length > 50000) throw new Error("草稿没有可恢复的节点，或内容超出画布限制。");
  const ids = new Set<string>();
  for (const node of draft.nodes) {
    if (!node || typeof node.id !== "string" || !node.id || ids.has(node.id) || !node.data || typeof node.data !== "object" || !node.position || !Number.isFinite(node.position.x) || !Number.isFinite(node.position.y)) throw new Error("草稿包含无效或重复的节点。");
    ids.add(node.id);
  }
  if (draft.edges.some(edge => !edge || !ids.has(edge.source) || !ids.has(edge.target))) throw new Error("草稿包含缺失端点的连线。");
  return draft;
}

function download(entry: Entry) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(entry.document, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = "画布恢复草稿.json"; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function DraftRecovery({ projectId, draftPrefix, onClose, onRestore }: { projectId: string; draftPrefix: string; onClose: () => void; onRestore: (draft: RecoverableCanvas) => Promise<void> }) {
  const file = useRef<HTMLInputElement>(null);
  const [imported, setImported] = useState<Entry[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [stored, setStored] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let disposed = false;
    setLoading(true);
    void (async () => {
    const result: Entry[] = [];
    try {
      for (const { key, document: value } of await listCanvasDrafts(draftPrefix)) {
        try {
          const document = parseCanvasDraft(value, projectId);
          const saved = document.saved_at || Number(key.split(":backup:")[1]) || 0;
          result.push({ key, document, name: `${key.includes(":backup:") ? "冲突备份" : "未完成草稿"} · ${saved ? new Date(saved).toLocaleString() : "时间未知"}` });
        } catch { /* A corrupt entry must not hide other recoverable drafts. */ }
      }
    } catch { if (!disposed) setError("无法读取本机草稿存储；仍可导入下载过的 JSON 备份。"); }
    if (!disposed) { setStored(result.sort((a, b) => (b.document.saved_at || 0) - (a.document.saved_at || 0))); setLoading(false); }
    })();
    return () => { disposed = true; };
  }, [draftPrefix, projectId]);
  const entries = [...imported, ...stored];
  const active = entries.find(item => item.key === selected) || entries[0];
  async function load(file: File | undefined) {
    if (!file) return;
    try {
      if (file.size > 100 * 1024 * 1024) throw new Error("草稿文件最大支持 100 MiB。");
      const document = parseCanvasDraft(JSON.parse(await file.text()), projectId);
      const entry = { key: crypto.randomUUID(), name: "导入文件 · " + file.name, document };
      setImported(items => [entry, ...items]); setSelected(entry.key); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <Modal title="草稿恢复" wide onClose={() => { if (!busy) onClose(); }} className="canvas-draft-dialog">
    <p>恢复内容会以副本加入当前画布，保留当前已保存的内容和原始备份。生成任务不会重复提交。</p>
    <button className="canvas-small-button" disabled={busy} onClick={() => file.current?.click()}><Upload size={15} />导入画布草稿 JSON</button>
    <input ref={file} type="file" accept=".json,application/json" hidden onChange={e => { void load(e.target.files?.[0]); e.target.value = ""; }} />
    <div className="canvas-draft-content"><nav aria-label="可恢复草稿">{entries.map(entry => <button key={entry.key} className={active?.key === entry.key ? "active" : ""} onClick={() => setSelected(entry.key)}><strong>{entry.name}</strong><small>{entry.document.nodes.length} 个节点 · {entry.document.edges.length} 条连线</small></button>)}{!entries.length && <p>{loading ? "正在读取本机草稿…" : "暂无本机草稿，可以导入之前下载的 JSON。"}</p>}</nav>
      {active && <div className="canvas-draft-preview"><strong>草稿预览</strong>{active.document.nodes.slice(0, 40).map(node => <article key={node.id}><b>{String(node.data.title || node.type || "节点")}</b><p>{String(node.data.text || node.data.note || (node.data.generation as { prompt?: string } | undefined)?.prompt || "媒体 / 布局节点").slice(0, 500)}</p></article>)}{active.document.nodes.length > 40 && <small>其余 {active.document.nodes.length - 40} 个节点也会一同恢复。</small>}</div>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <footer><button className="canvas-small-button" disabled={!active || busy} onClick={() => active && download(active)}><Download size={15} />下载选中草稿</button><button className="primary" disabled={!active || busy} onClick={async () => { if (!active) return; setBusy(true); setError(""); try { await onRestore(active.document); onClose(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); } }}><FolderOpen size={15} />{busy ? "正在恢复…" : "恢复为副本"}</button></footer>
  </Modal>;
}
