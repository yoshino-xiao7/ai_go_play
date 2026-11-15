import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
  ShieldCheck,
  X,
} from "lucide-react";
import { api, sizeText } from "../api";
import { Modal } from "../ui";
import type { SetupState } from "./types";
import DirectoryPicker from "./DirectoryPicker";
import useOnboarding from "./useOnboarding";
import { steps, titles, subtitles } from "./setupContent";
import WelcomeStep from "./WelcomeStep";
import EngineStep from "./EngineStep";
import ModelsStep from "./ModelsStep";
import ChecksStep from "./ChecksStep";
import IdentityStep from "./IdentityStep";

export default function Onboarding({
  initial,
  onComplete,
}: {
  initial: SetupState;
  onComplete: (state: SetupState, route: string) => void;
}) {
  const view = useOnboarding(initial, onComplete);
  const {
    state,
    error,
    setError,
    picker,
    setPicker,
    identity,
    account,
    privacy,
    manual,
    document,
    setDocument,
    documents,
    mainRef,
    step,
    index,
    busy,
    refresh,
    act,
    go,
    chooseDirectory,
    baseOnly,
    finish,
    jobRunning,
    canNext,
  } = view;
  return (
    <div className="setup-shell">
      <header className="setup-header">
        <a className="setup-brand" href="#/setup">
          <img src="/icon.svg" alt="" />
          <span>ai-go-play</span>
          <span className="setup-brand-divider" />
          <span className="setup-header-label">初次准备</span>
        </a>
        <span
          className="setup-local"
          title={state.busy ? state.job?.message : undefined}
        >
          {state.busy ? (
            <>
              <LoaderCircle size={13} className="setup-spin" />
              正在准备 {Math.round((state.job?.progress || 0) * 100)}%
            </>
          ) : (
            <>
              <span />
              进度保存在本机
            </>
          )}
        </span>
      </header>
      <div className="setup-layout">
        <aside className="setup-sidebar">
          <div>
            <p className="setup-overline">YOUR LOCAL STUDIO</p>
            <h2>从准备，到创作。</h2>
            <ol className="setup-step-list">
              {steps.map((s, i) => (
                <li
                  key={s.id}
                  className={i === index ? "current" : i < index ? "past" : ""}
                >
                  <button
                    onClick={() => i < index && !busy && void go(s.id)}
                    disabled={i >= index || busy}
                    aria-current={i === index ? "step" : undefined}
                  >
                    <span className="setup-step-number">
                      {i < index ? (
                        <Check size={15} />
                      ) : (
                        String(i + 1).padStart(2, "0")
                      )}
                    </span>
                    <span>
                      <strong>{s.name}</strong>
                      <small>{s.description}</small>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </div>
          <div className="setup-sidebar-note">
            <ShieldCheck size={20} />
            <p>
              创作文件留在本机。
              <br />
              是否分享，由你决定。
            </p>
          </div>
        </aside>
        <main className="setup-main" ref={mainRef}>
          <div className="setup-main-inner">
            <div className="setup-page-heading">
              <p className="setup-overline">
                {String(index + 1).padStart(2, "0")} / 05{" "}
                <span>{steps[index].name}</span>
              </p>
              <h1>{titles[step]}</h1>
              <p>{subtitles[step]}</p>
            </div>
            {error && (
              <div className="setup-error" role="alert">
                <span>{error}</span>
                <button aria-label="关闭错误提示" onClick={() => setError("")}>
                  <X size={16} />
                </button>
              </div>
            )}
            <section
              key={step}
              className="setup-stage"
              aria-label={steps[index].name}
            >
              {step === "welcome" && <WelcomeStep view={view} />}
              {step === "comfy" && <EngineStep view={view} />}
              {step === "models" && <ModelsStep view={view} />}
              {step === "verify" && <ChecksStep view={view} />}
              {step === "identity" && <IdentityStep view={view} />}
            </section>
            {state.job && (
              <div
                className={`setup-job ${state.job.status}`}
                role="status"
                aria-live="polite"
              >
                <div>
                  <span>
                    {jobRunning ? (
                      <LoaderCircle size={16} className="setup-spin" />
                    ) : state.job.status === "succeeded" ? (
                      <CheckCircle2 size={16} />
                    ) : (
                      <CircleHelp size={16} />
                    )}
                    <strong>{state.job.message}</strong>
                  </span>
                  {jobRunning ? (
                    <button
                      onClick={() =>
                        void act(async () => {
                          await api("/api/setup/jobs/cancel", {
                            method: "POST",
                          });
                          await refresh();
                        })
                      }
                    >
                      取消任务
                    </button>
                  ) : (
                    <span>
                      {state.job.status === "succeeded" ? "完成" : "可重试"}
                    </span>
                  )}
                </div>
                <div
                  className="setup-job-track"
                  role="progressbar"
                  aria-valuenow={Math.round(state.job.progress * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="准备任务进度"
                >
                  <i
                    style={{
                      width: `${Math.max(1, state.job.progress * 100)}%`,
                    }}
                  />
                </div>
                {!!state.job.total_bytes && (
                  <small>
                    {sizeText(state.job.completed_bytes || 0)} /{" "}
                    {sizeText(state.job.total_bytes)}
                  </small>
                )}
                {state.job.error && <pre>{state.job.error}</pre>}
                {state.job.result?.conflicts?.length ? (
                  <p>
                    以下文件未覆盖，请核对后重试：
                    {state.job.result.conflicts.join("、")}
                  </p>
                ) : null}
                {state.job.log_tail && (
                  <details>
                    <summary>查看安装日志</summary>
                    <pre>{state.job.log_tail}</pre>
                  </details>
                )}
              </div>
            )}
            <footer className="setup-footer">
              <div>
                {index > 0 ? (
                  <button
                    className="setup-back"
                    disabled={busy}
                    onClick={() => void go(steps[index - 1].id)}
                  >
                    <ArrowLeft size={16} />
                    上一步
                  </button>
                ) : (
                  <button
                    className="setup-back"
                    disabled={busy}
                    onClick={() => void baseOnly()}
                  >
                    仅使用基础画布
                  </button>
                )}
              </div>
              <div>
                {index > 0 && index < 4 && (
                  <button
                    className="setup-base-only"
                    disabled={busy}
                    onClick={() => void baseOnly()}
                  >
                    暂不准备模型
                  </button>
                )}
                {step === "identity" ? (
                  <button
                    className="btn setup-primary"
                    disabled={
                      busy ||
                      !privacy ||
                      !manual ||
                      (identity === "yike" && !account?.connected)
                    }
                    onClick={() => void finish()}
                  >
                    进入我的画布
                    <ArrowRight size={17} />
                  </button>
                ) : (
                  <button
                    className="btn setup-primary"
                    disabled={busy || !canNext}
                    onClick={() => void go(steps[index + 1].id)}
                  >
                    {step === "welcome" ? "开始准备" : "下一步"}
                    <ArrowRight size={17} />
                  </button>
                )}
              </div>
            </footer>
          </div>
        </main>
      </div>
      {picker && (
        <DirectoryPicker
          title={
            picker === "source"
              ? "选择模型下载目录"
              : picker === "models"
                ? "选择模型存放目录"
                : "选择 ComfyUI 目录"
          }
          onClose={() => setPicker(null)}
          onSelect={(p) => void chooseDirectory(p)}
        />
      )}
      {document && documents && (
        <Modal
          title={document === "privacy" ? "隐私条款" : "用户手册"}
          onClose={() => setDocument(null)}
        >
          <article className="setup-document">
            <p>版本 {documents.version} · ai-go-play 本地工作台</p>
            {documents[document].map((section) => (
              <section key={section.title}>
                <h3>{section.title}</h3>
                <p>{section.text}</p>
              </section>
            ))}
            <button
              className="btn setup-primary"
              onClick={() => setDocument(null)}
            >
              返回准备向导
              <ArrowRight size={16} />
            </button>
          </article>
        </Modal>
      )}
    </div>
  );
}
