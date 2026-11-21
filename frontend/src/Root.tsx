import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api";
import type { SetupState } from "./setup/types";
import Onboarding from "./setup/Onboarding";

const App = lazy(() => import("./shell/Studio"));

export default function Root() {
  const [state, setState] = useState<SetupState | null>(null);
  const [error, setError] = useState("");
  const [legacy, setLegacy] = useState(false);
  const [route, setRoute] = useState(location.hash);
  const refresh = useCallback(async () => {
    setError("");
    setLegacy(false);
    try {
      setState(await api<SetupState>("/api/setup"));
      setLegacy(false);
    } catch (e) {
      // An existing server may still be running the release before onboarding.
      // Do not strand its canvas (or restart its active generation jobs) when
      // an updated frontend is built into the same local source checkout.
      if (e instanceof ApiError && e.status === 404) {
        try {
          const health = await api<{ ok: boolean; version: string; root: string }>("/api/health");
          if (health.ok && health.version && health.root) {
            setLegacy(true);
            return;
          }
        } catch {
          // An unrelated server or unavailable API must not bypass setup.
        }
        setError("当前地址没有安装引导接口。请确认使用项目 start.cmd 启动的地址。");
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => {
    void refresh();
    const changed = () => setRoute(location.hash);
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, [refresh]);
  if (!state && !legacy)
    return (
      <main className="setup-loading setup-shell">
        <img src="/icon.svg" alt="" width="40" height="40" />
        <h1>{error ? "暂时无法连接本机服务" : "正在打开创作空间"}</h1>
        {error && (
          <>
            <p role="alert">{error}</p>
            <button
              className="btn setup-primary"
              onClick={() => void refresh()}
            >
              重新连接
            </button>
          </>
        )}
      </main>
    );
  // An existing library can predate onboarding. Keep it accessible on upgrade
  // without fabricating consent; explicitly opening #/setup still runs the guide.
  if (
    state && ((!state.existing_library_installation && (!state.completed ||
    state.consent?.privacy !== state.policy_version)) ||
    route.startsWith("#/setup"))
  )
    return (
      <Onboarding
        initial={state}
        onComplete={(next, target) => {
          setState(next);
          location.hash = target;
          setRoute("#" + target);
        }}
      />
    );
  if (legacy && route.startsWith("#/setup"))
    return (
      <main className="setup-loading setup-shell">
        <h1>安装引导需要更新本机服务</h1>
        <p>画布仍可正常使用。请等当前生成任务结束后，让 Agent 重新启动本机画布后端，再打开此页。重复双击 start.cmd 会继续复用现有服务。</p>
        <a className="btn setup-primary" href="#/">返回工作台</a>
        <button className="btn setup-secondary" onClick={() => void refresh()}>重新检查</button>
      </main>
    );
  return (
    <Suspense fallback={<main className="setup-loading">正在打开画布…</main>}>
      <App />
    </Suspense>
  );
}
