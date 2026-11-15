import {
  Check,
  Copy,
  Download,
  ExternalLink,
  FolderOpen,
  RefreshCw,
  X,
} from "lucide-react";
import type { OnboardingView } from "./useOnboarding";
import { sizeText } from "../api";

export default function ModelsStep({ view }: { view: OnboardingView }) {
  const {
    state,
    catalog,
    setError,
    modelPath,
    setModelPath,
    files,
    freeBytes,
    setPicker,
    copyDone,
    setCopyDone,
    busy,
    scanModels,
    act,
    save,
    job,
    togglePack,
    selectedFiles,
    bytes,
    iconFor,
  } = view;
  return (
    <>
      <div className="setup-share-banner">
        <div className="setup-share-icon">
          <Download size={23} />
        </div>
        <div>
          <strong>ai-go-play · 模型分享</strong>
          <span>
            夸克网盘{" "}
            <button
              className="setup-copy"
              onClick={() =>
                void navigator.clipboard
                  .writeText(catalog?.share.passcode || "BsXE")
                  .then(() => {
                    setCopyDone(true);
                    setTimeout(() => setCopyDone(false), 1800);
                  })
                  .catch(() =>
                    setError("无法自动复制，请手动输入提取码 BsXE。"),
                  )
              }
            >
              提取码 {catalog?.share.passcode || "BsXE"}
              {copyDone ? <Check size={12} /> : <Copy size={12} />}
            </button>
          </span>
        </div>
        <a
          className="btn setup-secondary"
          href={catalog?.share.url}
          target="_blank"
          rel="noreferrer"
        >
          打开夸克分享
          <ExternalLink size={15} />
        </a>
        {catalog?.mirrors?.map((mirror) => (
          <a key={mirror.id} className="btn setup-secondary" href={mirror.url} target="_blank" rel="noreferrer">
            打开{mirror.name}分享<ExternalLink size={15} />
          </a>
        ))}
      </div>
      <div className="setup-section-row">
        <h2>选择要准备的模型</h2>
        <button
          className="setup-text-button"
          disabled={busy}
          onClick={() => void job("share")}
        >
          <RefreshCw size={14} />
          扫描夸克目录
        </button>
      </div>
      <p className="setup-catalog-source">
        {state.share_scan
          ? `已读取夸克分享 · ${state.share_scan.files.filter((f) => f.status === "listed").length}/${catalog?.files.length || 48} 个文件名和大小匹配`
          : "当前显示项目内置发布清单，点击扫描可核对夸克在线目录。"}
      </p>
      {!!catalog?.mirrors?.length && <p className="setup-catalog-source">网盘任选其一下载，分类目录和导入方式相同，无需重复下载。大文件请使用对应网盘客户端；下载后仍需执行完整校验。</p>}
      <p className="setup-catalog-source">
        模型使用各自的许可证，部分限制商业用途、使用地区或托管服务。{" "}
        <a href="/api/setup/model-licenses" target="_blank" rel="noreferrer">
          查看模型来源与许可证
        </a>
      </p>
      <label className="setup-select-all">
        <input
          type="checkbox"
          checked={!!catalog && state.packs.length === catalog.packs.length}
          disabled={busy}
          onChange={(e) =>
            void act(async () => {
              await save({
                packs: e.target.checked
                  ? catalog?.packs.map((p) => p.id) || []
                  : [],
              });
              await scanModels();
            })
          }
        />
        <span>准备全部模型</span>
        <strong>{sizeText(bytes)}</strong>
      </label>
      <div className="setup-pack-grid">
        {catalog?.packs.map((pack) => (
          <label
            key={pack.id}
            className={`setup-pack ${state.packs.includes(pack.id) ? "selected" : ""}`}
          >
            <input
              type="checkbox"
              checked={state.packs.includes(pack.id)}
              disabled={busy}
              onChange={() => void togglePack(pack.id)}
            />
            <span className="setup-pack-icon">{iconFor(pack.id)}</span>
            <span>
              <strong>{pack.name}</strong>
              <small>{pack.description}</small>
            </span>
            <em>{sizeText(pack.bytes)}</em>
          </label>
        ))}
      </div>
      <p className="setup-soft-note">
        已选 {state.packs.length} 类，去重后 {selectedFiles.length} 个文件 ·{" "}
        {sizeText(bytes)}。共享文件只导入一次。
      </p>
      {selectedFiles.length > 0 && (
        <p className="setup-soft-note">
          所选功能的文件分布在分享中的这些目录：
          {[...new Set(selectedFiles.map((f) =>
            (state.share_scan?.files.find((remote) => remote.path === f.path)?.remote_path
              || f.download_path || `${f.packs[0]}/models/${f.path}`)
              .split("/models/")[0],
          ))].join("、")}。
          共享模型可能位于其他功能目录；下一步的缺失列表会显示每个文件的网盘位置。
        </p>
      )}
      <div className="setup-field">
        <label htmlFor="model-path">模型存放位置</label>
        <div className="setup-path-row">
          <input
            id="model-path"
            value={modelPath}
            onChange={(e) => setModelPath(e.target.value)}
            onBlur={() =>
              modelPath !== state.models_root &&
              void act(async () => {
                await save({ models_root: modelPath });
                await scanModels();
              })
            }
          />
          <button
            aria-label="选择模型存放目录"
            onClick={() => setPicker("models")}
          >
            <FolderOpen size={18} />
          </button>
        </div>
        <button
          className="setup-text-button"
          disabled={busy}
          onClick={() => {
            setModelPath(state.default_models_root);
            void act(async () => {
              await save({ models_root: state.default_models_root });
              await scanModels();
            });
          }}
        >
          使用默认位置
        </button>
        {freeBytes !== null && (
          <small className="setup-soft-note">
            目标磁盘可用 {sizeText(freeBytes)} · 所选模型需要 {sizeText(bytes)}
          </small>
        )}
      </div>
      <div className="setup-section-row">
        <h2>导入已下载的模型</h2>
        <button
          className="setup-text-button"
          disabled={busy}
          onClick={() => setPicker("source")}
        >
          <FolderOpen size={16} />
          选择下载目录
        </button>
      </div>
      <p className="setup-soft-note">
        从网盘下载后，选择保存的 ai-go-play
        文件夹。支持原始分类目录和已合并的 models 目录。
      </p>
      {state.import_sources.map((source) => (
        <div className="setup-source" key={source}>
          <FolderOpen size={15} />
          <span>{source}</span>
          <button
            aria-label={`移除来源 ${source}`}
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await save({
                  import_sources: state.import_sources.filter(
                    (p) => p !== source,
                  ),
                });
                await scanModels();
              })
            }
          >
            <X size={15} />
          </button>
        </div>
      ))}
      <div className="setup-import-summary">
        <span>
          <strong>
            {files.filter((f) => f.status === "unverified").length}
          </strong>{" "}
          已在目标位置 <span className="setup-summary-separator" />{" "}
          <strong>
            {files.filter((f) => f.source && f.status !== "unverified").length}
          </strong>{" "}
          可导入
        </span>
        <button
          className="btn setup-primary"
          disabled={busy || !files.some((f) => f.source)}
          onClick={() => void job("import")}
        >
          <Download size={16} />
          导入所选模型
        </button>
      </div>
      <small className="setup-soft-note">
        导入会复制并校验文件，不移动原件、不覆盖冲突文件。缺失项会在下一步列出。
      </small>
    </>
  );
}
