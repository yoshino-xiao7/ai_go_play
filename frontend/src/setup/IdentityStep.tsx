import {
  Check,
  CheckCircle2,
  ExternalLink,
  HardDrive,
  LoaderCircle,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import type { OnboardingView } from "./useOnboarding";

export default function IdentityStep({ view }: { view: OnboardingView }) {
  const {
    state,
    acting,
    identity,
    setIdentity,
    account,
    connection,
    setConnection,
    privacy,
    setPrivacy,
    manual,
    setManual,
    setDocument,
    connect,
  } = view;
  return (
    <>
      <div className="setup-identity-options">
        <button
          className={`setup-identity ${identity === "yike" ? "selected" : ""}`}
          onClick={() => setIdentity("yike")}
        >
          <UserRound size={25} />
          <span>
            <strong>亦可账号</strong>
            <small>连接账号，按需发布和分享作品</small>
          </span>
          <span className="setup-selection-dot">
            {identity === "yike" && <Check size={13} />}
          </span>
        </button>
        <button
          className={`setup-identity ${identity === "guest" ? "selected" : ""}`}
          onClick={() => setIdentity("guest")}
        >
          <HardDrive size={25} />
          <span>
            <strong>游客进入</strong>
            <small>使用完整的本地画布，稍后也可连接账号</small>
          </span>
          <span className="setup-selection-dot">
            {identity === "guest" && <Check size={13} />}
          </span>
        </button>
      </div>
      {identity === "yike" && (
        <div className="setup-account-panel">
          {account?.connected ? (
            <p className="setup-good">
              <CheckCircle2 size={20} />
              已连接 {account.user?.nickname || "亦可账号"}
            </p>
          ) : (
            <>
              <h2>在亦可网页注册或登录</h2>
              <p>通过官方授权页连接，完成后会自动回到这里的就绪状态。</p>
              <button
                className="btn setup-primary"
                disabled={acting || !!connection}
                onClick={() => void connect()}
              >
                {connection ? (
                  <LoaderCircle size={16} className="setup-spin" />
                ) : (
                  <ExternalLink size={16} />
                )}
                注册 / 登录并连接
              </button>
              {connection && (
                <>
                  <a
                    className="setup-external"
                    href={connection.authorize_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    重新打开授权页面
                    <ExternalLink size={14} />
                  </a>
                  <button
                    className="setup-text-button"
                    onClick={() => setConnection(null)}
                  >
                    重新发起连接
                  </button>
                </>
              )}
            </>
          )}
        </div>
      )}
      <div className="setup-consent">
        <ShieldCheck size={24} />
        <div>
          <h2>进入前，请阅读这两份说明</h2>
          <p>选择权始终在你手上。两个选项都不会默认勾选。</p>
          <label>
            <input
              type="checkbox"
              checked={privacy}
              onChange={(e) => setPrivacy(e.target.checked)}
            />
            <span>
              我已阅读并同意{" "}
              <button
                className="setup-document-link"
                onClick={(e) => {
                  e.preventDefault();
                  setDocument("privacy");
                }}
              >
                《隐私条款》
              </button>
            </span>
          </label>
          <label>
            <input
              type="checkbox"
              checked={manual}
              onChange={(e) => setManual(e.target.checked)}
            />
            <span>
              我已阅读并理解{" "}
              <button
                className="setup-document-link"
                onClick={(e) => {
                  e.preventDefault();
                  setDocument("manual");
                }}
              >
                《用户手册》
              </button>
            </span>
          </label>
        </div>
      </div>
      <p className="setup-soft-note">
        <CheckCircle2 size={14} />
        本地工作台已准备 ·{" "}
        {state.packs.length ? `${state.packs.length} 类模型` : "基础画布模式"} ·
        可随时在安装向导中调整
      </p>
    </>
  );
}
