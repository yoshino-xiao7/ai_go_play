// ⌘K / Ctrl+K command palette: jump to any project or view, run canvas commands, switch look.
// Fuzzy subsequence matching, keyboard first (↑ ↓ Enter Esc), a light bar that glides between rows.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight, BookOpen, CircuitBoard, Clapperboard, CornerDownLeft, Download, FilePlus2, Film, FolderKanban, GitBranch, History,
  Images, Moon, Search, Settings2, Share2, Sparkles, Spline, Sun, Trash2, UsersRound, Workflow, Zap,
} from "lucide-react";
import { api, mediaUrl } from "../api";
import type { Project } from "../types";
import { currentPalette, setPalette } from "../design/appearance";
import { sendCanvasCommand, type CanvasCommand } from "./canvasBridge";
import { useLayer } from "./layers";

type Item = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  keywords?: string;
  icon: React.ReactNode;
  cover?: string | null;
  run: () => void;
};

/** Score a fuzzy subsequence match; -1 when the query does not match. */
function score(text: string, query: string) {
  if (!query) return 0;
  const hay = text.toLowerCase();
  const needle = query.toLowerCase();
  const direct = hay.indexOf(needle);
  if (direct >= 0) return 1000 - direct * 3 - (hay.length - needle.length) * 0.1;
  let at = -1;
  let total = 0;
  let run = 0;
  for (const ch of needle) {
    const next = hay.indexOf(ch, at + 1);
    if (next < 0) return -1;
    run = next === at + 1 ? run + 1 : 0;
    total += 10 + run * 6 - Math.min(9, next - at);
    at = next;
  }
  return total;
}

export function useCommandPaletteHotkey(open: () => void) {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); open(); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [open]);
}

export default function CommandPalette({
  onClose, navigate, projectId, openComfy, toggleTray, newProject,
}: {
  onClose: () => void;
  navigate: (to: string) => void;
  projectId: string | null;
  openComfy: () => void;
  toggleTray: () => void;
  newProject: () => void;
}) {
  const [query, setQuery] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [active, setActive] = useState(0);
  const [closing, setClosing] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const shadeRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let alive = true;
    api<Project[]>("/api/projects").then(list => { if (alive) setProjects(list); }).catch(() => undefined);
    return () => { alive = false; };
  }, []);

  const close = () => { setClosing(true); window.setTimeout(onClose, 170); };
  // On the shared layer stack: Esc (handled below while typing) or a click on the blank area
  // returns focus to whatever opened the palette; an action that opens its own layer keeps it.
  useLayer(true, close, { ref: shadeRef });
  const act = (fn: () => void) => () => { close(); window.setTimeout(fn, 60); };

  const items = useMemo<Item[]>(() => {
    const p = projectId ? `/canvas/${encodeURIComponent(projectId)}` : null;
    const list: Item[] = [
      { id: "new", group: "创作", label: "新建画布", hint: "从空白或模板开始", keywords: "new create xinjian", icon: <FilePlus2 size={17} />, run: act(newProject) },
    ];
    if (p) {
      const canvas = (label: string, command: CanvasCommand, icon: React.ReactNode, hint: string) =>
        ({ id: `cmd-${command}`, group: "当前画布", label, hint, keywords: command, icon, run: act(() => sendCanvasCommand(command)) });
      list.push(
        canvas("导出 / 分享", "share", <Share2 size={17} />, "分享到亦可或导出"),
        canvas("分镜成片", "production", <Clapperboard size={17} />, "把分镜串成成片"),
        canvas("自动编排", "orchestrate", <Workflow size={17} />, "按依赖批量运行"),
        canvas("口型同步", "lipsync", <Zap size={17} />, "LatentSync"),
        canvas("在画布中搜索", "search", <Search size={17} />, "节点与提示词"),
        canvas("草稿恢复", "drafts", <History size={17} />, "本机自动保存"),
        canvas("导出画布 JSON", "export", <Download size={17} />, "备份结构"),
      );
    }
    const views: [string, string, React.ReactNode, string, boolean?][] = [
      ["项目", "/projects", <FolderKanban size={17} />, "projects xiangmu"],
      ["画布", p || "", <Spline size={17} />, "canvas huabu", true],
      ["剧本", p ? `${p}/script` : "", <BookOpen size={17} />, "script juben", true],
      ["主体", p ? `${p}/subjects` : "", <UsersRound size={17} />, "subjects zhuti", true],
      ["时间线", p ? `${p}/timeline` : "", <Film size={17} />, "timeline shijianxian", true],
      ["素材库", "/assets", <Images size={17} />, "assets sucai library"],
      ["工作流", "/workflows", <GitBranch size={17} />, "workflows gongzuoliu"],
      ["设置", "/settings", <Settings2 size={17} />, "settings shezhi"],
      ["回收站", "/trash", <Trash2 size={17} />, "trash huishouzhan"],
    ];
    for (const [label, to, icon, keywords, needs] of views) {
      if (needs && !to) continue;
      list.push({ id: `go-${label}`, group: "前往", label, keywords, icon, hint: to, run: act(() => navigate(to)) });
    }
    const pearl = currentPalette() === "pearl";
    list.push(
      { id: "engine", group: "系统", label: "引擎 · ComfyUI", hint: "启动、模型、日志", keywords: "comfy engine yinqing", icon: <CircuitBoard size={17} />, run: act(openComfy) },
      { id: "tray", group: "系统", label: "显影槽", hint: "全部生成任务", keywords: "tray tasks jobs xianying", icon: <Sparkles size={17} />, run: act(toggleTray) },
      { id: "palette", group: "系统", label: pearl ? "切换到 夜场 Nocturne" : "切换到 珍珠 Pearl", hint: "外观", keywords: "theme dark light palette", icon: pearl ? <Moon size={17} /> : <Sun size={17} />, run: act(() => setPalette(pearl ? "nocturne" : "pearl")) },
    );
    for (const project of [...projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at))) {
      list.push({
        id: `p-${project.id}`, group: "项目", label: project.name, hint: project.aspect_ratio === "free" ? "自由画布" : project.aspect_ratio,
        keywords: project.id, icon: <ArrowRight size={17} />, cover: project.cover_version_id ? mediaUrl(project.cover_version_id) : null,
        run: act(() => navigate(`/canvas/${encodeURIComponent(project.id)}`)),
      });
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, projectId]);

  const results = useMemo(() => {
    const q = query.trim();
    if (!q) return items.filter(item => item.group !== "项目").concat(items.filter(item => item.group === "项目").slice(0, 6));
    return items
      .map(item => ({ item, s: Math.max(score(item.label, q), score(item.keywords || "", q) - 40) }))
      .filter(entry => entry.s >= 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 24)
      .map(entry => entry.item);
  }, [items, query]);

  useEffect(() => { setActive(0); }, [query]);

  // The highlight bar glides to the active row.
  useLayoutEffect(() => {
    const row = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    const bar = barRef.current;
    if (!row || !bar) { if (bar) bar.style.opacity = "0"; return; }
    bar.style.opacity = "1";
    bar.style.transform = `translateY(${row.offsetTop}px)`;
    bar.style.height = `${row.offsetHeight}px`;
    row.scrollIntoView({ block: "nearest" });
  }, [active, results]);

  const keyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") { event.preventDefault(); setActive(i => Math.min(results.length - 1, i + 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive(i => Math.max(0, i - 1)); }
    else if (event.key === "Enter") { event.preventDefault(); results[active]?.run(); }
    else if (event.key === "Escape") { event.preventDefault(); close(); }
  };

  let lastGroup = "";
  return (
    <div ref={shadeRef} className={`cmdk-shade ${closing ? "is-closing" : ""}`} onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="命令面板" onKeyDown={keyDown}>
        <div className="cmdk-input">
          <Search size={19} />
          <input autoFocus placeholder="搜索项目、视图或命令…" value={query} onChange={event => setQuery(event.target.value)}
            aria-controls="cmdk-list" aria-activedescendant={results[active] ? `cmdk-${results[active].id}` : undefined} />
          <kbd>Esc</kbd>
        </div>
        <div className="cmdk-list" id="cmdk-list" role="listbox" ref={listRef}>
          <span className="cmdk-bar" ref={barRef} aria-hidden="true" />
          {results.length === 0 && <p className="cmdk-empty">没有匹配“{query}”的内容</p>}
          {results.map((item, index) => {
            const head = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <div key={item.id} className="cmdk-group-wrap">
                {head && <div className="cmdk-group">{head}</div>}
                <button id={`cmdk-${item.id}`} role="option" aria-selected={index === active} data-index={index}
                  className={`cmdk-item ${index === active ? "is-active" : ""}`} style={{ "--i": index } as React.CSSProperties}
                  onMouseMove={() => setActive(index)} onClick={item.run}>
                  <span className="cmdk-icon">{item.cover ? <img src={item.cover} alt="" onError={event => { event.currentTarget.hidden = true; }} /> : item.icon}</span>
                  <span className="cmdk-label">{item.label}</span>
                  {item.hint && <small>{item.hint}</small>}
                  {index === active && <CornerDownLeft className="cmdk-enter" size={14} />}
                </button>
              </div>
            );
          })}
        </div>
        <footer className="cmdk-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>Enter</kbd> 执行</span><span><kbd>Ctrl</kbd><kbd>K</kbd> 随时唤起</span>
        </footer>
      </div>
    </div>
  );
}
