import { useEffect, useState } from "react";
import {
  ArrowUpRight, BookOpen, CheckCircle2, CircleHelp, Copy, Download,
  ExternalLink, Github, Info, LoaderCircle, MessageCircle, RefreshCw, ShieldCheck,
} from "lucide-react";
import { api, ApiError } from "./api";
import { Loading, Modal } from "./ui";
import "./about.css";

type Update = {
  status: "available" | "up_to_date" | "ahead" | "unavailable";
  reason: string;
  message: string;
  current_version: string;
  checked_at: string;
  cached: boolean;
  retry_after_seconds: number;
  latest: null | {
    version: string; tag: string; name: string; published_at: string;
    notes: string; notes_truncated: boolean; url: string;
  };
};
type AboutInfo = {
  name: string; version: string; channel: string;
  repository: string; repository_url: string; releases_url: string;
  community_qq: string; license: string; license_text: string;
  runtime: { system: string; architecture: string; python: string };
  update: Update | null;
};
type Documents = {
  version: string;
  privacy: { title: string; text: string }[];
  manual: { title: string; text: string }[];
};
type DocumentKind = "privacy" | "manual" | "license";
const titles = { privacy: "隐私说明", manual: "用户手册", license: "开源许可证" };
const timeText = (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false });

export default function About({ notify }: { notify: (message: string, error?: boolean) => void }) {
  const [info, setInfo] = useState<AboutInfo | null>(null);
  const [error, setError] = useState("");
  const [update, setUpdate] = useState<Update | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState("");
  const [document, setDocument] = useState<DocumentKind | null>(null);
  const [documents, setDocuments] = useState<Documents | null>(null);
  const [documentError, setDocumentError] = useState("");
  const [loadKey, setLoadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<AboutInfo>("/api/about", { signal: controller.signal }).then((next) => {
      setInfo(next);
      setUpdate(next.update);
    }).catch((e) => {
      if (!controller.signal.aborted) setError(e instanceof ApiError && e.status === 404
        ? "当前本机服务尚不支持关于页。请等创作任务结束后，从“退出程序”正常关闭服务，再运行 start.cmd。"
        : "无法读取应用信息，请检查本机服务后重试。");
    });
    return () => controller.abort();
  }, [loadKey]);

  useEffect(() => {
    if (!document || document === "license" || documents) return;
    const controller = new AbortController();
    setDocumentError("");
    api<Documents>("/api/setup/documents", { signal: controller.signal })
      .then(setDocuments).catch(() => {
        if (!controller.signal.aborted) setDocumentError("无法读取本机说明，请关闭后重试。");
      });
    return () => controller.abort();
  }, [document, documents]);

  async function check() {
    setChecking(true);
    setCheckError("");
    try {
      setUpdate(await api<Update>("/api/about/updates/check", {
        method: "POST", signal: AbortSignal.timeout(20000),
      }));
    } catch {
      setCheckError("本次检查未完成，请确认本机服务连接正常后重试。");
    } finally {
      setChecking(false);
    }
  }

  async function copy(text: string, success: string) {
    try {
      await navigator.clipboard.writeText(text);
      notify(success);
    } catch {
      notify("浏览器未允许复制，请选中页面中的文字手动复制。", true);
    }
  }

  const diagnostic = info ? [
    `${info.name} ${info.version}`,
    `系统：${info.runtime.system} / ${info.runtime.architecture}`,
    `Python：${info.runtime.python}`,
    `更新源：${info.repository} · 正式 Releases`,
    `最近检查：${update ? `${update.status} (${update.checked_at})` : "未检查"}`,
  ].join("\n") : "";
  const updateTitle = checking ? "正在连接 GitHub…" : checkError ? "检查未完成" : !update ? "检查新的正式版本"
    : ({ available: `有新版本 v${update.latest?.version}`, up_to_date: "已是最新正式版本", ahead: "当前版本领先于正式发布", unavailable: "暂时无法确认更新" })[update.status];

  return (
    <div className="page about-page">
      <div className="page-topline"><span className="breadcrumb">工作台 <span>/</span> 关于</span></div>
      <header className="page-heading">
        <div><h1>关于 ai-go-play</h1><p>为创作者与 Agent 准备的本地 AI 创作工作台。</p></div>
      </header>
      {error ? <div className="error-banner" role="alert"><Info size={18} /><span>{error}</span><button onClick={() => setLoadKey((n) => n + 1)}>重试</button></div> : !info ? <Loading /> : <>
        <div className="about-overview">
          <section className="about-identity" aria-labelledby="about-identity-title">
            <img src="/icon.svg" width="64" height="64" alt="" />
            <div className="about-wordmark"><h2 id="about-identity-title">ai-go-play</h2><span className="about-version">v{info.version}</span></div>
            <p className="about-motto">你决定故事，AI 协作完成创作。</p>
            <p className="about-description">把故事、角色、镜头、声音和生成过程放在同一张无限画布上。你指挥、选择与审阅，AI 分工完成创作，画布保留每一步。</p>
            <div className="about-principles"><span>AI to AI</span><span>本地保存</span><span>开放协作</span></div>
          </section>
          <section className="about-update" aria-labelledby="about-update-title" aria-busy={checking}>
            <div className="about-section-label"><Download size={18} /><h2 id="about-update-title">版本与更新</h2><span>正式版通道</span></div>
            <div className="about-update-result" role="status" aria-live="polite">
              {checking ? <LoaderCircle className="about-spin" size={25} /> : update?.status === "up_to_date" && !checkError ? <CheckCircle2 size={25} /> : <RefreshCw size={25} />}
              <h3>{updateTitle}</h3>
              <p>{checking ? "正在读取上游的正式 Release。" : checkError || update?.message || "从 GitHub 获取版本信息、更新说明与官方下载入口。"}</p>
            </div>
            <div className="about-update-actions">
              <button className={`button ${update?.status === "available" && !checkError ? "secondary" : "primary"}`} onClick={() => void check()} disabled={checking}>
                <RefreshCw size={16} className={checking ? "about-spin" : ""} />{checking ? "正在检查…" : "检查更新"}
              </button>
              {update?.status === "available" && update.latest && !checkError && <a className="button primary" href={update.latest.url} target="_blank" rel="noreferrer">查看发布与下载<ArrowUpRight size={16} /></a>}
            </div>
            <p className="about-check-time">{update ? `上次检查：${timeText(update.checked_at)}${update.cached ? " · 缓存结果" : ""}` : `当前版本 v${info.version} · 尚未检查`}</p>
            {update?.cached && <p className="about-small">此结果缓存 {Math.ceil(update.retry_after_seconds / 60)} 分钟；从上次检查时间起算，到期后可再次查询。</p>}
            <p className="about-small">仅在点击时连接 GitHub，不发送作品、账号或本机路径。检查更新不会安装软件或中断创作。</p>
            <a className="about-text-link" href={info.releases_url} target="_blank" rel="noreferrer">浏览全部 Releases <ExternalLink size={14} /></a>
          </section>
        </div>

        {update?.latest && <section className="about-release" aria-label="上游发布说明">
          <div className="about-release-heading"><h2>上游发布 · {update.latest.tag}</h2><span>{timeText(update.latest.published_at)}</span></div>
          <details open={update.status === "available"}><summary>查看更新说明</summary><pre className="about-release-notes">{update.latest.notes || "此版本尚未提供更新说明，请查看 GitHub 发布页。"}</pre>
            <a className="about-text-link" href={update.latest.url} target="_blank" rel="noreferrer">{update.latest.notes_truncated ? "查看完整发布说明" : "在 GitHub 查看此版本"}<ExternalLink size={14} /></a>
          </details>
          {update.status === "available" && <p className="about-upgrade-tip">更新前先保存项目，等待任务完成，通过“退出程序”关闭本机服务并备份资料库与配置，再按 Release 说明安装新版本。</p>}
        </section>}

        <div className="about-details-grid">
          <section className="about-section" aria-labelledby="about-community-title">
            <h2 id="about-community-title">项目与社区</h2>
            <a className="about-resource" href={info.repository_url} target="_blank" rel="noreferrer"><Github size={20} /><span><strong>GitHub 源码</strong><small>{info.repository}</small></span><ArrowUpRight size={17} /></a>
            <a className="about-resource" href={`${info.repository_url}/issues/new/choose`} target="_blank" rel="noreferrer"><CircleHelp size={20} /><span><strong>反馈问题与建议</strong><small>通过 GitHub Issues 与维护者交流</small></span><ArrowUpRight size={17} /></a>
            <button className="about-resource" onClick={() => void copy(info.community_qq, "已复制 QQ 群号，在 QQ 中搜索即可加入。") }><MessageCircle size={20} /><span><strong>QQ 交流群 · {info.community_qq}</strong><small>复制群号，交流创作与使用经验</small></span><Copy size={17} /></button>
            <a className="about-resource" href={`${info.repository_url}/blob/main/CONTRIBUTING.md`} target="_blank" rel="noreferrer"><Github size={20} /><span><strong>参与项目贡献</strong><small>了解开发流程与贡献规范</small></span><ArrowUpRight size={17} /></a>
          </section>
          <section className="about-section" aria-labelledby="about-help-title">
            <h2 id="about-help-title">帮助与使用说明</h2>
            <button className="about-resource" onClick={() => setDocument("manual")}><BookOpen size={20} /><span><strong>用户手册</strong><small>准备环境、使用画布与备份作品</small></span><ArrowUpRight size={17} /></button>
            <button className="about-resource" onClick={() => setDocument("privacy")}><ShieldCheck size={20} /><span><strong>隐私说明</strong><small>了解本机保存、联网与账号授权</small></span><ArrowUpRight size={17} /></button>
            <a className="about-resource" href="#/setup"><Download size={20} /><span><strong>安装与模型向导</strong><small>检查本机环境，准备创作所需模型</small></span><ArrowUpRight size={17} /></a>
            <a className="about-resource" href={`${info.repository_url}/blob/main/docs/README.md`} target="_blank" rel="noreferrer"><BookOpen size={20} /><span><strong>文档中心</strong><small>开发、运维与 API 使用文档</small></span><ArrowUpRight size={17} /></a>
          </section>
        </div>

        <section className="about-runtime" aria-labelledby="about-runtime-title">
          <div className="about-runtime-heading"><h2 id="about-runtime-title">运行信息</h2><button className="button secondary" onClick={() => void copy(diagnostic, "已复制运行信息，不含账号、作品或本机路径。") }><Copy size={15} />复制运行信息</button></div>
          <dl><div><dt>应用版本</dt><dd>{info.version}</dd></div><div><dt>操作系统</dt><dd>{info.runtime.system} · {info.runtime.architecture}</dd></div><div><dt>Python</dt><dd>{info.runtime.python}</dd></div><div><dt>源码许可</dt><dd><button className="about-text-link" onClick={() => setDocument("license")}>{info.license} License <ArrowUpRight size={14} /></button></dd></div></dl>
          <details><summary>查看可复制的运行摘要</summary><pre className="about-release-notes">{diagnostic}</pre></details>
        </section>
        <footer className="about-footer"><p>由 ai-go-play 贡献者共同建设。感谢 React、React Flow、FastAPI、ComfyUI、FFmpeg 及模型社区。</p><p>源码采用 MIT 许可；模型及第三方组件遵循各自许可证。<a className="about-text-link" href="/api/setup/model-licenses" target="_blank" rel="noreferrer">查看模型许可 <ExternalLink size={13} /></a></p></footer>
        {document && <Modal title={titles[document]} onClose={() => setDocument(null)} wide className="about-document">
          {document === "license" ? <><pre className="about-license-text">{info.license_text || "本机未包含许可证全文，请查看上游文件。"}</pre><a className="about-text-link" href={`${info.repository_url}/blob/main/LICENSE`} target="_blank" rel="noreferrer">查看上游 LICENSE <ExternalLink size={14} /></a></> : documentError ? <p role="alert">{documentError}</p> : !documents ? <Loading /> : <>
            <p className="about-small">说明版本：{documents.version}</p>
            {documents[document].map((item) => <section key={item.title}><h3>{item.title}</h3><p>{item.text}</p></section>)}
            {document === "privacy" && <section><h3>检查更新</h3><p>点击“检查更新”时，本机服务会访问 GitHub 公开 Releases 接口，获取版本信息。请求不包含作品、账号或本机路径；GitHub 会接收到发起请求的网络地址。检查结果仅缓存在本机服务内存中。</p></section>}
          </>}
        </Modal>}
      </>}
    </div>
  );
}
