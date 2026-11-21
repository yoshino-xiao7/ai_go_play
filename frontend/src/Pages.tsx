// Page views of the studio shell: projects, material library, asset inspector, trash, settings.
// The shell (shell/Studio.tsx) owns routing, the rail, the top bar and the tray.
import StudioSelect from "./StudioSelect";
import AppearanceSettings from "./AppearanceSettings";
import CreationStarter from "./CreationStarter";
import ReelOrbit from "./shell/ReelOrbit";
import { motionReduced } from "./design/appearance";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  AudioLines,
  BookOpen,
  Clapperboard,
  Clock3,
  Cloud,
  ExternalLink,
  Film,
  Folder,
  FolderOpen,
  HardDrive,
  Image as ImageIcon,
  Info,
  Layers2,
  MoreHorizontal,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  AlertCircle,
  ArchiveRestore,
  PackageOpen,
} from "lucide-react";
import { api, dateText, mediaUrl, sizeText, uploadAsset } from "./api";
import type {
  Asset,
  AssetPage,
  AssetVersion,
  Project,
  StorageInfo,
} from "./types";
import { Confirm, EmptyState, Loading, Modal } from "./ui";
import { Button, ButtonLink, IconButton } from "./design/Button";

const ACCEPT =
  ".png,.jpg,.jpeg,.webp,.gif,.mp4,.mov,.webm,.mkv,.wav,.mp3,.m4a,.flac,.ogg";
const typeNames: Record<string, string> = {
  image: "图片",
  video: "视频",
  audio: "音频",
  upload: "上传",
  import: "导入",
  generated: "生成",
  comfyui: "ComfyUI 生成",
  openai: "OpenAI 生成",
};
const kindIcon = (type: string, size = 18) =>
  type === "video" ? (
    <Film size={size} />
  ) : type === "audio" ? (
    <AudioLines size={size} />
  ) : (
    <ImageIcon size={size} />
  );
type Notify = (message: string, error?: boolean) => void;

/** A number that counts up (ease-out) whenever it changes. */
function CountUp({ value }: { value: number }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    if (motionReduced()) { setShown(value); from.current = value; return; }
    const start = performance.now();
    const origin = from.current;
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / 900);
      const eased = 1 - Math.pow(1 - k, 4);
      setShown(Math.round(origin + (value - origin) * eased));
      if (k < 1) raf = requestAnimationFrame(step); else from.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{shown}</>;
}
const navigate = (target: string) => {
  window.location.hash = target;
};

export function Projects({
  refresh,
  onChanged,
  notify,
  shareSite = "https://yk.yukiryou.icu",
}: {
  refresh: number;
  onChanged: () => void;
  notify: Notify;
  shareSite?: string;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<Project | "new" | null>(null);
  const [creatingGuide, setCreatingGuide] = useState(false);
  const [name, setName] = useState("");
  const [aspect, setAspect] = useState("free");
  const [busy, setBusy] = useState(false);
  const [shareImportOpen, setShareImportOpen] = useState(false);
  const [shareLink, setShareLink] = useState("");
  const [shareImportError, setShareImportError] = useState("");
  const [shareImporting, setShareImporting] = useState(false);
  const [menu, setMenu] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [eagerCoverCount, setEagerCoverCount] = useState(0);
  useEffect(() => {
    let active = true;
    api<Project[]>("/api/projects")
      .then((value) => {
        if (active) {
          setProjects(value);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refresh]);
  const startEdit = (project: Project | "new", guide = false) => {
    setCreatingGuide(guide);
    setEditing(project);
    setName(project === "new" ? (guide ? "我的第一个 AI 镜头" : "") : project.name);
    setAspect(project === "new" ? "free" : project.aspect_ratio);
    setMenu(null);
  };
  // The command palette (shell) can ask for a new canvas from anywhere.
  useEffect(() => {
    const open = () => {
      try { sessionStorage.removeItem("manju:intent"); } catch { /* optional */ }
      startEdit("new");
    };
    try { if (sessionStorage.getItem("manju:intent") === "new-project") open(); } catch { /* optional */ }
    window.addEventListener("manju:new-project", open);
    return () => window.removeEventListener("manju:new-project", open);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim() || !editing) return;
    setBusy(true);
    try {
      const value = await api<Project>(
        editing === "new" ? "/api/projects" : `/api/projects/${editing.id}`,
        {
          method: editing === "new" ? "POST" : "PATCH",
          body: JSON.stringify({ name: name.trim(), aspect_ratio: aspect }),
        },
      );
      setEditing(null);
      onChanged();
      if (editing === "new") navigate(`/canvas/${value.id}${creatingGuide ? "/guide" : ""}`);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const duplicate = async (project: Project) => {
    setMenu(null);
    try {
      await api(`/api/projects/${project.id}/duplicate`, { method: "POST" });
      onChanged();
      notify("已复制项目，素材沿用原资产");
    } catch (e) {
      notify((e as Error).message, true);
    }
  };
  const importProject = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    const body = new FormData();
    body.append("file", file);
    try {
      const project = await api<Project>("/api/projects/import", {
        method: "POST",
        body,
      });
      onChanged();
      notify("项目包已导入");
      navigate(`/canvas/${project.id}`);
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
      if (importRef.current) importRef.current.value = "";
    }
  };
  const importSharedCanvas = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!shareLink.trim() || shareImporting) return;
    setShareImporting(true);
    setShareImportError("");
    try {
      const project = await api<Project & { omitted_history: number }>("/api/share/import", {
        method: "POST",
        body: JSON.stringify({ link: shareLink.trim() }),
      });
      setShareImportOpen(false);
      setShareLink("");
      onChanged();
      notify(project.omitted_history ? `已导入本地，跳过 ${project.omitted_history} 个无法下载原件的历史素材` : "亦可画布已导入本地");
      navigate(`/canvas/${project.id}`);
    } catch (e) {
      setShareImportError((e as Error).message);
    } finally {
      setShareImporting(false);
    }
  };
  const filtered = projects.filter((item) =>
    item.name.toLowerCase().includes(search.toLowerCase()),
  );

  useLayoutEffect(() => {
    const grid = gridRef.current;
    const scrollport = grid?.closest("main");
    if (!grid || !scrollport) return;

    const measure = () => {
      // Keep the fold anchored to the top of the project list when it is scrolled.
      const fold = scrollport.getBoundingClientRect().bottom - scrollport.scrollTop;
      let count = 0;
      for (const card of grid.children) {
        if (card.getBoundingClientRect().top >= fold) break;
        count += 1;
      }
      setEagerCoverCount(count);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    observer.observe(scrollport);
    return () => observer.disconnect();
  }, [error, filtered.length, loading]);

  const latest = [...projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  return (
    <div className="page projects-page">
      <section className="proj-hero">
        <div className="proj-hero-copy">
          <p className="eyebrow"><span className="eyebrow-dot" />Local Reel Studio · 本地影视工作台</p>
          <h1 className="display kinetic" aria-label="让每一帧都在本机显影">
            {["让每一帧", "都在本机", "显影"].map((line, row) => (
              <span className={`kinetic-line ${row === 2 ? "is-spectrum" : ""}`} key={line} aria-hidden="true">
                {Array.from(line).map((ch, i) => <span className="kinetic-ch" key={i} style={{ "--i": row * 5 + i } as React.CSSProperties}>{ch}</span>)}
              </span>
            ))}
          </h1>
          <p className="lede">项目、素材、生成结果和引擎都在这台电脑上。写下镜头，连起节点，看它们一帧帧显影。</p>
          <div className="proj-hero-actions">
            <Button variant="primary" className="big hero-cta" data-magnetic="0.25" onClick={() => startEdit("new")}><Plus size={18} />新建画布</Button>
            <Button variant="secondary" className="big" disabled={busy} onClick={() => importRef.current?.click()}><PackageOpen size={17} />导入项目包</Button>
          </div>
          <div className="proj-hero-more">
            <button className="chip" onClick={() => startEdit("new", true)}><BookOpen size={14} />新手引导</button>
            <button className="chip" onClick={() => { setShareImportError(""); setShareImportOpen(true); }}><Cloud size={14} />从亦可导入</button>
            {latest && <button className="chip chip-continue" onClick={() => navigate(`/canvas/${latest.id}`)}><ArrowRight size={14} />继续「{latest.name}」</button>}
          </div>
          <dl className="proj-stats">
            <div style={{ "--i": 0 } as React.CSSProperties}><dt>项目</dt><dd><CountUp value={projects.length} /></dd></div>
            <div style={{ "--i": 1 } as React.CSSProperties}><dt>已有封面</dt><dd><CountUp value={projects.filter(p => p.cover_version_id).length} /></dd></div>
            <div style={{ "--i": 2 } as React.CSSProperties}><dt>最近编辑</dt><dd className="is-text">{latest ? dateText(latest.updated_at) : "—"}</dd></div>
          </dl>
        </div>
        <ReelOrbit projects={projects} onOpen={id => navigate(`/canvas/${id}`)} />
      </section>
      <input ref={importRef} type="file" accept=".manju,.zip" hidden onChange={(e) => importProject(e.target.files?.[0])} />
      {!loading && !error && <CreationStarter projects={projects} onOpen={id => { onChanged(); navigate(`/canvas/${id}`); }} notify={notify} />}
      <div className="shelf-head">
        <h2>最近项目 <span className="count">{search ? filtered.length : projects.length}</span></h2>
        <span className="shelf-sort"><Clock3 size={14} />按最近编辑</span>
        <div className="search-field">
          <Search size={15} />
          <input placeholder="搜索项目" aria-label="搜索项目" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>
      {error && (
        <div className="error-banner"><AlertCircle size={18} /><span>{error}</span><button onClick={onChanged}>重新连接</button></div>
      )}
      {loading ? <Loading /> : filtered.length === 0 ? (
        error ? null : (
          <EmptyState
            icon={search ? <Search size={27} /> : <Layers2 size={30} strokeWidth={1.5} />}
            title={search ? "没有匹配的项目" : "还没有项目"}
            description={search ? `找不到包含“${search}”的项目。` : "新建一张画布，或导入已有的 ai-go-play 项目包。"}
            action={search ? <Button variant="secondary" onClick={() => setSearch("")}>清除搜索</Button>
              : <Button variant="primary" onClick={() => startEdit("new")}><Plus size={17} />新建画布</Button>}
          />
        )
      ) : (
        <div className="shelf" ref={gridRef}>
          {filtered.map((project, index) => (
            <article className={menu === project.id ? "reel is-menu-open" : "reel"} key={project.id} data-tilt="7" style={{ "--i": Math.min(index, 18) } as React.CSSProperties}>
              <span className="reel-holo" aria-hidden="true" />
              <button className="reel-cover" onClick={() => navigate(`/canvas/${project.id}`)} aria-label={`打开 ${project.name}`}>
                <span className="reel-blank" aria-hidden="true"><Layers2 size={30} strokeWidth={1.2} /></span>
                {project.cover_version_id && (
                  <img key={project.cover_version_id} src={mediaUrl(project.cover_version_id)} alt="" loading={index < eagerCoverCount ? "eager" : "lazy"} decoding="async" onError={(e) => { e.currentTarget.hidden = true; }} />
                )}
                <span className="reel-open"><ArrowRight size={18} /></span>
              </button>
              <div className="reel-caption">
                <button className="reel-name" title={project.name} onClick={() => navigate(`/canvas/${project.id}`)}>
                  <strong>{project.name}</strong>
                  <small>{project.aspect_ratio === "free" ? "自由画布" : project.aspect_ratio} · 编辑于 {dateText(project.updated_at)}</small>
                </button>
                <div className="menu-wrap">
                  <IconButton aria-label={`${project.name} 操作`} aria-expanded={menu === project.id} onClick={() => setMenu(menu === project.id ? null : project.id)}>
                    <MoreHorizontal size={18} />
                  </IconButton>
                  {menu === project.id && (
                    <div className="dropdown">
                      <button onClick={() => startEdit(project)}>重命名与画幅</button>
                      <button onClick={() => duplicate(project)}>复制项目</button>
                      <a href={`/api/projects/${project.id}/export`} onClick={() => setMenu(null)}>导出项目包</a>
                      <button className="text-danger" onClick={() => { setDeleting(project); setMenu(null); }}>移入回收站</button>
                    </div>
                  )}
                </div>
              </div>
              <div className="reel-tags">
                <span className="tag">本地</span>
                {project.cover_version_id ? <span className="tag accent">已有封面</span> : <span className="tag">空白</span>}
              </div>
            </article>
          ))}
        </div>
      )}
      {shareImportOpen && (
        <Modal title="从亦可导入画布" onClose={() => { if (!shareImporting) setShareImportOpen(false); }}>
          <form onSubmit={importSharedCanvas}>
            <div className="modal-body form-stack">
              <p>在亦可画布广场打开作品，复制地址栏中的作品链接。导入后会生成可编辑的本地副本。</p>
              <ButtonLink variant="secondary" href={`${shareSite}/canvas`} target="_blank" rel="noreferrer">
                浏览亦可画布广场 <ExternalLink size={15} />
              </ButtonLink>
              <label>
                亦可作品链接
                <input
                  autoFocus
                  required
                  maxLength={2048}
                  type="url"
                  placeholder={`${shareSite}/s/…`}
                  disabled={shareImporting}
                  value={shareLink}
                  onChange={(e) => { setShareLink(e.target.value); setShareImportError(""); }}
                />
              </label>
              <p>此处只能获取公开作品。仅发布了封面、没有可下载文件的历史视频会跳过。</p>
              {shareImporting && <p role="status">正在下载并校验素材。素材较多时需要几分钟。</p>}
              {shareImportError && <div className="error-banner" role="alert">{shareImportError}</div>}
            </div>
            <footer className="modal-footer">
              {shareLink.trim() && !shareImporting && (
                <ButtonLink variant="secondary" href={`/api/share/export?link=${encodeURIComponent(shareLink.trim())}`} target="_blank" rel="noreferrer">
                  <ArrowDownToLine size={16} /> 下载 .manju
                </ButtonLink>
              )}
              <Button variant="primary" disabled={!shareLink.trim() || shareImporting}>
                {shareImporting ? "正在导入…" : "导入并打开"}
              </Button>
            </footer>
          </form>
        </Modal>
      )}
      {editing && (
        <Modal
          title={creatingGuide ? "创建练习画布" : editing === "new" ? "新建画布" : "项目设置"}
          onClose={() => setEditing(null)}
        >
          <form onSubmit={save}>
            <div className="modal-body form-stack">
              {creatingGuide && <p>做一段简单的视频。你可以先生成一张图，也可以用本机图片。不想继续时，随时跳过引导。</p>}
              <label>
                项目名称
                <input
                  autoFocus
                  required
                  maxLength={160}
                  placeholder="例如：人物设定 / 第一集分镜"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <label>
                输出画幅偏好
                <StudioSelect
                  value={aspect}
                  onChange={(e) => setAspect(e.target.value)}
                >
                  <option value="free">自由画布</option>
                  <option value="16:9">横屏 16:9</option>
                  <option value="9:16">竖屏 9:16</option>
                </StudioSelect>
              </label>
            </div>
            <footer className="modal-footer">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditing(null)}
              >
                {creatingGuide ? "暂不开始" : "取消"}
              </Button>
              <Button
                variant="primary"
                disabled={busy || !name.trim()}
              >
                {busy ? "保存中…" : creatingGuide ? "创建画布并开始" : editing === "new" ? "创建画布" : "保存"}
              </Button>
            </footer>
          </form>
        </Modal>
      )}
      {deleting && (
        <Confirm
          title="将项目移入回收站？"
          description={`“${deleting.name}”可以在回收站恢复。`}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            try {
              await api(`/api/projects/${deleting.id}`, { method: "DELETE" });
              setDeleting(null);
              onChanged();
            } catch (e) {
              notify((e as Error).message, true);
            }
          }}
        />
      )}
    </div>
  );
}

export function Library({
  refresh,
  onChanged,
  onPreview,
  notify,
  uploadFiles,
}: {
  refresh: number;
  onChanged: () => void;
  onPreview: (version: string) => void;
  notify: Notify;
  uploadFiles: (files: FileList | File[]) => void;
}) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [tag, setTag] = useState("");
  const [source, setSource] = useState("");
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState(false);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<Asset | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  useEffect(() => {
    setPage(0);
  }, [search, type, tag, source]);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(
      () => {
        const params = new URLSearchParams({
          search,
          type,
          tag,
          source,
          offset: String(page * 40),
          limit: "40",
        });
        api<AssetPage>(`/api/assets?${params}`)
          .then((value) => {
            if (active) {
              setAssets(value.items);
              setTotal(value.total);
              setError("");
            }
          })
          .catch((e) => {
            if (active) setError(e.message);
          })
          .finally(() => {
            if (active) setLoading(false);
          });
      },
      search || tag ? 200 : 0,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [refresh, search, type, tag, source, page]);
  return (
    <div
      className={`page library-page ${dragging ? "drag-target" : ""}`}
      onDragEnter={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          dragDepth.current++;
          setDragging(true);
        }
      }}
      onDragLeave={() => {
        dragDepth.current--;
        if (dragDepth.current <= 0) setDragging(false);
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
      }}
    >
      <div className="page-topline">
        <span className="breadcrumb">
          工作台 <span>/</span> 资产库
        </span>
        <span className="local-label">
          <HardDrive size={14} />
          本地资料库
        </span>
      </div>
      <header className="page-heading">
        <div>
          <h1>
            资产库<span className="count">{total}</span>
          </h1>
          <p>统一保存素材，在每一张画布中自由引用。</p>
        </div>
        <button
          className="button primary btn"
          onClick={() => input.current?.click()}
        >
          <Upload size={17} />
          上传素材
        </button>
      </header>
      <input
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        ref={input}
        onChange={(e) => {
          if (e.target.files) uploadFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <div className="section-toolbar">
        <div className="tabs">
          {[
            ["", "全部"],
            ["image", "图片"],
            ["video", "视频"],
            ["audio", "音频"],
          ].map(([value, text]) => (
            <button
              key={value}
              className={type === value ? "active" : ""}
              onClick={() => setType(value)}
            >
              {value && kindIcon(value, 15)}
              {text}
            </button>
          ))}
        </div>
        <div className="button-row">
          <div className="search-field">
            <Search size={17} />
            <input
              placeholder="搜索素材名称"
              aria-label="搜索素材名称"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button
            className={`icon-button filter-button ${filters ? "active" : ""}`}
            aria-label="筛选标签与来源"
            onClick={() => setFilters(!filters)}
          >
            <SlidersHorizontal size={18} />
          </button>
        </div>
      </div>
      {filters && (
        <div className="filter-row">
          <label>
            标签
            <input
              placeholder="输入标签"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
            />
          </label>
          <label>
            来源
            <StudioSelect value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">全部来源</option>
              <option value="upload">上传</option>
              <option value="import">项目导入</option>
              <option value="generated">生成</option>
              <option value="comfyui">ComfyUI 生成</option>
              <option value="openai">OpenAI 生成</option>
            </StudioSelect>
          </label>
          <button
            className="button ghost"
            onClick={() => {
              setTag("");
              setSource("");
              setSearch("");
              setType("");
            }}
          >
            清除筛选
          </button>
        </div>
      )}
      {error && (
        <div className="error-banner">
          <AlertCircle size={18} />
          {error}
          <button onClick={onChanged}>重试</button>
        </div>
      )}
      {loading ? (
        <Loading />
      ) : assets.length === 0 ? (
        <EmptyState
          icon={<ImageIcon size={34} strokeWidth={1.3} />}
          title={
            search || type || tag || source
              ? "没有找到匹配素材"
              : "让第一份素材入场"
          }
          description={
            search || type || tag || source
              ? "调整搜索或筛选条件，查看其他素材。"
              : "拖入图片、视频或音频，也可以从电脑选择文件。"
          }
          action={
            <button
              className="button secondary"
              onClick={() => input.current?.click()}
            >
              <Plus size={17} />
              选择文件
            </button>
          }
        />
      ) : (
        <div className="asset-grid">
          {assets.map((asset) => (
            <article
              className="asset-card card"
              key={asset.id}
              draggable
              onDragStart={(e) =>
                e.dataTransfer.setData(
                  "application/x-manju-asset",
                  JSON.stringify(asset),
                )
              }
            >
              <button
                className={`asset-cover m-zoom ${asset.type}`}
                onClick={() => onPreview(asset.current_version_id)}
                aria-label={`预览 ${asset.name}`}
              >
                {asset.version.missing ? (
                  <div className="media-placeholder missing">
                    <AlertCircle size={26} />
                    <span>文件缺失</span>
                  </div>
                ) : asset.type === "audio" ? (
                  <div className="audio-cover">
                    <AudioLines size={42} strokeWidth={1.3} />
                    <span>
                      {asset.version.duration
                        ? `${asset.version.duration.toFixed(1)} 秒`
                        : "音频"}
                    </span>
                  </div>
                ) : (
                  <img
                    src={`${mediaUrl(asset.current_version_id)}&state=${asset.version.preview_status}`}
                    alt={asset.name}
                    loading="lazy"
                    onLoad={(e) => {
                      e.currentTarget.style.opacity = "1";
                    }}
                    onError={(e) => {
                      e.currentTarget.style.opacity = "0";
                    }}
                  />
                )}
                <span className="media-kind">
                  {kindIcon(asset.type, 13)}
                  {typeNames[asset.type]}
                </span>
                {asset.version_count > 1 && (
                  <span className="version-badge">
                    {asset.version_count} 个版本
                  </span>
                )}
              </button>
              <div className="asset-caption">
                <button onClick={() => onPreview(asset.current_version_id)}>
                  <strong title={asset.name}>{asset.name}</strong>
                  <small>
                    {asset.version.width
                      ? `${asset.version.width} × ${asset.version.height} · `
                      : ""}
                    {sizeText(asset.version.size)}
                  </small>
                </button>
                <button
                  className="icon-button"
                  aria-label={`回收 ${asset.name}`}
                  onClick={() => setDeleting(asset)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
              {asset.tags.length > 0 && (
                <div className="asset-tags">
                  {asset.tags.slice(0, 3).map((value) => (
                    <button
                      key={value}
                      onClick={() => {
                        setTag(value);
                        setFilters(true);
                      }}
                    >
                      {value}
                    </button>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      {total > 40 && (
        <div className="pagination">
          <button
            className="button secondary"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
          >
            上一页
          </button>
          <span>
            {page + 1} / {Math.ceil(total / 40)}
          </span>
          <button
            className="button secondary"
            disabled={(page + 1) * 40 >= total}
            onClick={() => setPage(page + 1)}
          >
            下一页
          </button>
        </div>
      )}
      {dragging && (
        <div className="drop-overlay">
          <Upload size={32} />
          <strong>松开以导入本地资产库</strong>
        </div>
      )}
      {deleting && (
        <Confirm
          title="将素材移入回收站？"
          description={`“${deleting.name}”的项目引用会先进行检查，仍被使用的素材会列出对应项目。`}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            try {
              await api(`/api/assets/${deleting.id}`, { method: "DELETE" });
              setDeleting(null);
              onChanged();
            } catch (e) {
              notify((e as Error).message, true);
              setDeleting(null);
              onPreview(deleting.current_version_id);
            }
          }}
        />
      )}
    </div>
  );
}

export function AssetInspector({
  versionId,
  onClose,
  notify,
  onChanged,
}: {
  versionId: string;
  onClose: () => void;
  notify: Notify;
  onChanged: () => void;
}) {
  const [asset, setAsset] = useState<Asset | null>(null);
  const [version, setVersion] = useState<AssetVersion | null>(null);
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const replace = useRef<HTMLInputElement>(null);
  const repair = useRef<HTMLInputElement>(null);
  const load = useCallback(async (id: string) => {
    try {
      const value = await api<{ version: AssetVersion; asset: Asset }>(
        `/api/versions/${id}`,
      );
      setAsset(value.asset);
      setVersion(value.version);
      setName(value.asset.name);
      setTags(value.asset.tags.join(", "));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load(versionId);
  }, [versionId, load]);
  useEffect(() => {
    if (!version || !asset) return;
    let active = true;
    const update = (event: Event) => {
      const payload = (event as CustomEvent).detail;
      if (
        payload.type !== "asset.updated" ||
        (payload.data?.version_id !== version.id &&
          payload.data?.asset_id !== asset.id)
      )
        return;
      void api<{ version: AssetVersion; asset: Asset }>(
        `/api/versions/${version.id}`,
      )
        .then((value) => {
          if (!active) return;
          setVersion(value.version);
          setAsset(value.asset);
        })
        .catch(() => {});
    };
    window.addEventListener("manju:event", update);
    return () => {
      active = false;
      window.removeEventListener("manju:event", update);
    };
  }, [version?.id, asset?.id]);
  const save = async () => {
    if (!asset || !name.trim()) return;
    setBusy(true);
    try {
      await api(`/api/assets/${asset.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          tags: tags
            .split(/[,，]/)
            .map((t) => t.trim())
            .filter(Boolean),
        }),
      });
      onChanged();
      notify("资产信息已保存");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  const changeFile = async (file: File, fixing: boolean) => {
    if (!asset || !version) return;
    setBusy(true);
    try {
      if (fixing) {
        const body = new FormData();
        body.append("file", file);
        body.append("version_id", version.id);
        await api(`/api/assets/${asset.id}/repair`, { method: "POST", body });
        await load(version.id);
      } else {
        const updated = await uploadAsset(file, { assetId: asset.id });
        await load(updated.current_version_id);
      }
      onChanged();
      notify(fixing ? "原件已修复" : "已创建新版本，可在画布属性中替换引用");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="资产详情" onClose={onClose} wide>
      {error ? (
        <div className="modal-body error-text">{error}</div>
      ) : !asset || !version ? (
        <Loading />
      ) : (
        <div className="asset-inspector">
          <div className="inspector-media checkerboard">
            {version.missing ? (
              <EmptyState
                icon={<AlertCircle size={30} />}
                title="原始文件缺失"
                description="选择内容相同的原文件，即可修复所有画布中的引用。"
                action={
                  <button
                    className="button secondary"
                    onClick={() => repair.current?.click()}
                  >
                    重新导入原文件
                  </button>
                }
              />
            ) : asset.type === "image" ? (
              <img src={mediaUrl(version.id, "original")} alt={asset.name} />
            ) : asset.type === "video" ? (
              <video
                key={`${version.id}-${version.preview_status}`}
                controls
                preload="metadata"
                poster={mediaUrl(version.id)}
                src={`${mediaUrl(version.id, "preview")}&state=${version.preview_status}`}
              />
            ) : (
              <div className="audio-player">
                <AudioLines size={64} strokeWidth={1} />
                <img
                  className="waveform"
                  src={`${mediaUrl(version.id, "waveform")}&state=${version.preview_status}`}
                  alt="音频波形"
                  onLoad={(e) => {
                    e.currentTarget.style.display = "block";
                  }}
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
                <audio
                  key={`${version.id}-${version.preview_status}`}
                  controls
                  src={`${mediaUrl(version.id, "preview")}&state=${version.preview_status}`}
                />
              </div>
            )}
          </div>
          <aside className="asset-detail form-stack">
            <span className="asset-type-label">
              {kindIcon(asset.type, 15)}
              {typeNames[asset.type]}资产
            </span>
            <label>
              显示名称
              <input
                value={name}
                maxLength={240}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              标签
              <input
                aria-label="标签"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="角色, 场景, 参考…"
              />
              <small>使用逗号分隔</small>
            </label>
            <button
              className="button secondary"
              disabled={busy || !name.trim()}
              onClick={save}
            >
              保存信息
            </button>
            <div className="detail-separator" />
            <label>
              文件版本
              <StudioSelect
                value={version.id}
                onChange={(e) => {
                  const selected = asset.versions?.find(
                    (v) => v.id === e.target.value,
                  );
                  if (selected) setVersion(selected);
                }}
              >
                {(asset.versions || [asset.version]).map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.id === asset.current_version_id ? "最新 · " : ""}
                    {item.filename} · {dateText(item.created_at)}
                  </option>
                ))}
              </StudioSelect>
            </label>
            <dl className="metadata">
              <dt>原文件</dt>
              <dd title={version.filename}>{version.filename}</dd>
              <dt>大小</dt>
              <dd>{sizeText(version.size)}</dd>
              {version.width && (
                <>
                  <dt>尺寸</dt>
                  <dd>
                    {version.width} × {version.height}
                  </dd>
                </>
              )}
              {version.duration != null && (
                <>
                  <dt>时长</dt>
                  <dd>{version.duration.toFixed(2)} 秒</dd>
                </>
              )}
              <dt>来源</dt>
              <dd>{typeNames[asset.source] || asset.source}</dd>
              <dt>预览</dt>
              <dd>
                {version.preview_status === "ready"
                  ? "已就绪"
                  : version.preview_status === "failed"
                    ? "生成失败，可在任务中重试"
                    : "正在生成"}
              </dd>
            </dl>
            <div className="button-row">
              <button
                className="button secondary compact"
                disabled={busy}
                onClick={() => replace.current?.click()}
              >
                <Upload size={15} />
                上传新版本
              </button>
              <a
                className="button secondary compact"
                href={mediaUrl(version.id, "original", true)}
              >
                <ArrowDownToLine size={15} />
                原件
              </a>
            </div>
            <label>
              存放位置
              <div className="file-location" title={version.path}>
                {version.path}
              </div>
            </label>
            <button
              className="text-button"
              onClick={async () => {
                try {
                  await api(`/api/assets/${asset.id}/reveal`, {
                    method: "POST",
                    body: JSON.stringify({ version_id: version.id }),
                  });
                } catch (e) {
                  notify((e as Error).message, true);
                }
              }}
            >
              <FolderOpen size={15} />
              打开所在文件夹
            </button>
            <div className="detail-separator" />
            {!!asset.subject_references?.length && <>
              <label>主体库引用</label>
              <div className="subject-reference-list">{asset.subject_references.map(subject => <span key={subject.id}>{subject.name}</span>)}</div>
              <p className="muted small">可在画布的“素材 → 主体库”管理。移除主体引用后才能删除该资产。</p>
              <div className="detail-separator" />
            </>}
            <label>引用项目</label>
            {asset.references?.length ? (
              <div className="reference-list">
                {asset.references.map((reference) => (
                  <button
                    key={reference.id}
                    onClick={() => {
                      onClose();
                      navigate(
                        reference.deleted_at
                          ? "/trash"
                          : `/canvas/${reference.id}`,
                      );
                    }}
                  >
                    <Folder size={15} />
                    <span>
                      {reference.name}
                      {reference.deleted_at ? " · 回收站" : ""}
                    </span>
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
            ) : (
              <p className="muted small">尚未添加到项目</p>
            )}
          </aside>
        </div>
      )}
      <input
        ref={replace}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          if (e.target.files?.[0]) void changeFile(e.target.files[0], false);
          e.target.value = "";
        }}
      />
      <input
        ref={repair}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          if (e.target.files?.[0]) void changeFile(e.target.files[0], true);
          e.target.value = "";
        }}
      />
    </Modal>
  );
}

export function Trash({
  refresh,
  onChanged,
  notify,
}: {
  refresh: number;
  onChanged: () => void;
  notify: Notify;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tab, setTab] = useState("projects");
  const [deleting, setDeleting] = useState<{
    id: string;
    name: string;
    type: string;
  } | null>(null);
  useEffect(() => {
    Promise.all([
      api<Project[]>("/api/projects?trash=true"),
      api<AssetPage>("/api/assets?trash=true&limit=200"),
    ])
      .then(([p, a]) => {
        setProjects(p);
        setAssets(a.items);
      })
      .catch((e) => notify(e.message, true));
  }, [refresh, notify]);
  const restore = async (type: string, id: string) => {
    try {
      await api(`/api/${type}/${id}/restore`, { method: "POST" });
      onChanged();
      notify("已恢复");
    } catch (e) {
      notify((e as Error).message, true);
    }
  };
  const items = tab === "projects" ? projects : assets;
  return (
    <div className="page">
      <div className="page-topline">
        <span className="breadcrumb">
          工作台 <span>/</span> 回收站
        </span>
      </div>
      <header className="page-heading">
        <div>
          <h1>回收站</h1>
          <p>恢复暂时收起的项目与素材，或永久清理它们。</p>
        </div>
      </header>
      <div className="section-toolbar">
        <div className="tabs">
          <button
            className={tab === "projects" ? "active" : ""}
            onClick={() => setTab("projects")}
          >
            项目 <span>{projects.length}</span>
          </button>
          <button
            className={tab === "assets" ? "active" : ""}
            onClick={() => setTab("assets")}
          >
            资产 <span>{assets.length}</span>
          </button>
        </div>
      </div>
      {items.length === 0 ? (
        <EmptyState
          icon={<Trash2 size={32} strokeWidth={1.3} />}
          title="回收站是空的"
          description="移入回收站的内容会出现在这里。"
        />
      ) : (
        <div className="trash-list">
          {items.map((item) => (
            <div className="trash-row" key={item.id}>
              <div className="trash-icon">
                {tab === "projects" ? (
                  <Folder size={22} />
                ) : (
                  kindIcon((item as Asset).type, 22)
                )}
              </div>
              <div className="trash-name">
                <strong>{item.name}</strong>
                <small>{dateText(item.deleted_at)} 移入回收站</small>
              </div>
              <button
                className="button secondary compact"
                onClick={() => restore(tab, item.id)}
              >
                <ArchiveRestore size={15} />
                恢复
              </button>
              <button
                className="icon-button text-danger"
                title="永久删除"
                onClick={() => setDeleting({ ...item, type: tab })}
              >
                <Trash2 size={17} />
              </button>
            </div>
          ))}
        </div>
      )}
      {deleting && (
        <Confirm
          title="永久删除？"
          description={`“${deleting.name}”将永久清理。此操作完成后无法从回收站恢复。`}
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            try {
              await api(`/api/${deleting.type}/${deleting.id}/permanent`, {
                method: "DELETE",
              });
              setDeleting(null);
              onChanged();
            } catch (e) {
              notify((e as Error).message, true);
            }
          }}
        />
      )}
    </div>
  );
}

export function StorageSettings({
  refresh,
  onChanged,
  notify,
}: {
  refresh: number;
  onChanged: () => void;
  notify: Notify;
}) {
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [section, setSection] = useState<"library" | "migration" | "media" | "appearance">("library");
  const [target, setTarget] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(
    () =>
      api<StorageInfo>("/api/settings/storage")
        .then((value) => {
          setStorage(value);
          setError("");
        })
        .catch((e) => setError(e.message)),
    [],
  );
  useEffect(() => {
    void load();
  }, [refresh, load]);
  useEffect(() => {
    if (
      !storage?.migration ||
      !["running", "copying", "switching", "pending"].includes(
        storage.migration.status,
      )
    )
      return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [storage?.migration?.status, load]);
  const migrate = async () => {
    setBusy(true);
    try {
      await api("/api/settings/storage/migrate", {
        method: "POST",
        body: JSON.stringify({ target: target.trim() }),
      });
      setConfirm(false);
      onChanged();
      void load();
      notify("资料库迁移任务已提交");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page settings-page">
      <div className="page-topline">
        <span className="breadcrumb">
          工作台 <span>/</span> 设置
        </span>
      </div>
      <header className="page-heading">
        <div>
          <h1>设置</h1>
          <p>管理素材原件、预览缓存和项目数据的保存位置。</p>
        </div>
      </header>
      {error && (
        <div className="error-banner">
          <AlertCircle size={18} />
          {error}
          <button onClick={load}>重试</button>
        </div>
      )}
      {!storage ? (
        <Loading />
      ) : (
        <div className="management-layout storage-layout">
          <nav className="management-nav" aria-label="设置分类">
            <span className="management-nav-label">工作台设置</span>
            <button aria-current={section === "library" ? "page" : undefined} onClick={() => setSection("library")}><HardDrive size={18} />本地存储</button>
            <button aria-current={section === "migration" ? "page" : undefined} onClick={() => setSection("migration")}><FolderOpen size={18} />资料库迁移</button>
            <button aria-current={section === "media" ? "page" : undefined} onClick={() => setSection("media")}><Clapperboard size={18} />媒体处理</button>
            <button aria-current={section === "appearance" ? "page" : undefined} onClick={() => setSection("appearance")}><Sparkles size={18} />外观与动效</button>
            <a href="#/about"><Info size={18} />关于与检查更新</a>
            <p>创作数据保存在本机，可随时查看保存位置与处理环境。</p>
          </nav>
        <div className="settings-stack">
          <section className="settings-card" hidden={section !== "library"}>
            <div className="setting-icon">
              <HardDrive size={24} />
            </div>
            <div className="setting-body">
              <h2>资料库目录</h2>
              <div className="path-box">{storage.root}</div>
              <div className="storage-stats">
                <span>
                  <strong>{sizeText(storage.size_bytes)}</strong>已使用
                </span>
                <span>
                  <strong>{sizeText(storage.free_bytes)}</strong>磁盘可用
                </span>
              </div>
              <p className="muted small">
                上传素材与后续生成的素材统一保存在此目录。
              </p>
            </div>
          </section>
          <section className="settings-card" hidden={section !== "migration"}>
            <div className="setting-icon">
              <FolderOpen size={24} />
            </div>
            <div className="setting-body">
              <h2>迁移资料库</h2>
              <p>
                填写一个空的本机目录。系统复制并校验文件，完成后启用新的位置。
              </p>
              <div className="inline-form">
                <input
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder="例如 E:\\ai_go_play_data"
                  aria-label="新资料库目录"
                />
                <button
                  className="button secondary"
                  disabled={
                    !target.trim() ||
                    busy ||
                    ["running", "copying", "switching", "pending"].includes(
                      storage.migration?.status || "",
                    )
                  }
                  onClick={() => setConfirm(true)}
                >
                  迁移
                </button>
              </div>
              {storage.migration && (
                <div className="migration-status">
                  <span>
                    迁移状态 ·{" "}
                    {(
                      {
                        running: "进行中",
                        copying: "复制中",
                        switching: "正在切换目录",
                        completed: "已完成",
                        failed: "失败",
                        interrupted: "已中断",
                        cancelled: "已取消",
                      } as Record<string, string>
                    )[storage.migration.status] || storage.migration.status}
                  </span>
                  <small>{storage.migration.target}</small>
                  {["copying", "switching"].includes(
                    storage.migration.status,
                  ) && (
                    <progress
                      value={storage.migration.progress || 0}
                      max={100}
                    />
                  )}
                  {storage.migration.error && (
                    <p className="error-text">{storage.migration.error}</p>
                  )}
                  {["failed", "interrupted", "paused"].includes(
                    storage.migration.status,
                  ) && (
                    <div className="button-row">
                      {["resume", "cancel"].map((action) => (
                        <button
                          className="button secondary compact"
                          key={action}
                          onClick={async () => {
                            try {
                              await api(
                                `/api/settings/storage/migration/${action}`,
                                { method: "POST" },
                              );
                              onChanged();
                              void load();
                            } catch (e) {
                              notify((e as Error).message, true);
                            }
                          }}
                        >
                          {action === "resume" ? "继续迁移" : "返回原目录"}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
          <section className="settings-card" hidden={section !== "media"}>
            <div className="setting-icon">
              <Clapperboard size={24} />
            </div>
            <div className="setting-body">
              <h2>媒体处理</h2>
              <dl className="runtime-details">
                <dt>FFmpeg</dt>
                <dd className={storage.ffmpeg ? "" : "error-text"}>
                  {storage.ffmpeg || "未找到，音视频预览暂不可用"}
                </dd>
                <dt>ffprobe</dt>
                <dd className={storage.ffprobe ? "" : "error-text"}>
                  {storage.ffprobe || "未找到，音视频信息探测暂不可用"}
                </dd>
              </dl>
              <p className="muted small">
                用于视频封面、音频波形及浏览器兼容预览。图片预览由本机直接处理。
              </p>
            </div>
          </section>
          {section === "appearance" && <AppearanceSettings />}
        </div>
        </div>
      )}
      {confirm && (
        <Confirm
          title="迁移本地资料库？"
          description={`将资料库复制到 ${target}。迁移期间暂停写入，完成校验后自动切换。`}
          busy={busy}
          onClose={() => setConfirm(false)}
          onConfirm={migrate}
        />
      )}
    </div>
  );
}
