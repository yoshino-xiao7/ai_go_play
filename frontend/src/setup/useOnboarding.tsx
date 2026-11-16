import { useCallback, useEffect, useRef, useState } from "react";
import { AudioLines, Film, Image } from "lucide-react";
import { api } from "../api";
import type { ShareStatus } from "../types";
import type {
  Catalog,
  ComfyState,
  Installation,
  ModelScan,
  Readiness,
  SetupState,
  Step,
} from "./types";
import { steps } from "./setupContent";
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
type Documents = {
  version: string;
  privacy: { title: string; text: string }[];
  manual: { title: string; text: string }[];
};

export default function useOnboarding(
  initial: SetupState,
  onComplete: (state: SetupState, route: string) => void,
) {
  const [state, setState] = useState(initial),
    [catalog, setCatalog] = useState<Catalog | null>(null),
    [error, setError] = useState(""),
    [acting, setActing] = useState(false);
  const [comfy, setComfy] = useState<ComfyState | null>(null),
    [candidates, setCandidates] = useState<Installation[]>([]),
    [scanned, setScanned] = useState(false),
    [scanning, setScanning] = useState(false);
  const [installPath, setInstallPath] = useState(initial.default_comfy_path),
    [manualPath, setManualPath] = useState(""),
    [port, setPort] = useState(8188);
  const [modelPath, setModelPath] = useState(initial.models_root),
    [modelScan, setModelScan] = useState<ModelScan | null>(null),
    [readiness, setReadiness] = useState<Readiness | null>(null);
  const [picker, setPicker] = useState<
      "comfy" | "install" | "models" | "source" | null
    >(null),
    [copyDone, setCopyDone] = useState(false),
    [showMissing, setShowMissing] = useState(false);
  const [identity, setIdentity] = useState<"guest" | "yike">("guest"),
    [account, setAccount] = useState<ShareStatus | null>(null),
    [connection, setConnection] = useState<{
      request_id: string;
      authorize_url: string;
    } | null>(null);
  const [privacy, setPrivacy] = useState(false),
    [manual, setManual] = useState(false),
    [document, setDocument] = useState<"privacy" | "manual" | null>(null),
    [documents, setDocuments] = useState<Documents | null>(null);
  const mainRef = useRef<HTMLDivElement>(null),
    lastJob = useRef<string>(""),
    shareAttempted = useRef(false),
    portInitialized = useRef(false);
  const step = state.step,
    index = steps.findIndex((s) => s.id === step),
    busy = acting || state.busy;
  const files = modelScan?.files || [];
  const refresh = useCallback(async () => {
    setState(await api<SetupState>("/api/setup"));
  }, []);
  const refreshComfy = useCallback(async () => {
    setComfy(await api<ComfyState>("/api/comfy"));
  }, []);
  const scanModels = useCallback(async () => {
    setModelScan(await api<ModelScan>("/api/setup/models"));
  }, []);
  const checkReady = useCallback(async () => {
    setReadiness(await api<Readiness>("/api/setup/readiness"));
  }, []);
  async function act(work: () => Promise<void>) {
    setError("");
    setActing(true);
    try {
      await work();
    } catch (e) {
      setError(message(e));
    } finally {
      setActing(false);
    }
  }
  async function save(patch: Partial<SetupState>) {
    const next = await api<SetupState>("/api/setup", {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
    setState(next);
    return next;
  }
  async function go(next: Step) {
    await act(async () => {
      if (step === "models" && modelPath !== state.models_root)
        await save({ models_root: modelPath });
      await save({ step: next });
      mainRef.current?.scrollTo({ top: 0 });
    });
  }
  async function startJob(kind: string, extra: Record<string, unknown> = {}) {
    await api("/api/setup/jobs", {
      method: "POST",
      body: JSON.stringify({ kind, ...extra }),
    });
    await refresh();
  }
  function job(kind: string, extra: Record<string, unknown> = {}) {
    return act(() => startJob(kind, extra));
  }
  function useExistingModels(path: string) {
    return act(async () => {
      const next = await save({ models_root: path, step: "verify" });
      setModelPath(next.models_root);
      mainRef.current?.scrollTo({ top: 0 });
      await startJob("verify");
    });
  }
  async function scanComfy(path?: string) {
    setScanned(true);
    setScanning(true);
    setError("");
    try {
      const r = await api<{ installations: Installation[] }>(
        "/api/comfy/scan",
        { method: "POST", body: JSON.stringify(path ? { path } : {}) },
      );
      setCandidates(r.installations);
      setScanned(true);
    } catch (e) {
      setError(message(e));
    } finally {
      setScanning(false);
    }
  }
  async function selectComfy(path: string) {
    await act(async () => {
      setComfy(
        await api<ComfyState>("/api/comfy/settings", {
          method: "PUT",
          body: JSON.stringify({ installation_path: path, port }),
        }),
      );
    });
  }
  async function chooseDirectory(path: string) {
    const target = picker;
    setPicker(null);
    if (target === "install") setInstallPath(path);
    if (target === "comfy") {
      setManualPath(path);
      await selectComfy(path);
    }
    if (target === "models") {
      setModelPath(path);
      await act(async () => {
        await save({ models_root: path });
        await scanModels();
      });
    }
    if (target === "source")
      await act(async () => {
        await save({ import_sources: [...state.import_sources, path] });
        await scanModels();
      });
  }
  async function baseOnly() {
    await act(async () => {
      await save({ packs: [], step: "identity" });
    });
  }
  async function togglePack(id: string) {
    const selected = state.packs.includes(id);
    let packs = selected
      ? state.packs.filter((p) => p !== id)
      : [...state.packs, id];
    if (selected && id === "05-indextts")
      packs = packs.filter((p) => p !== "06-indextts-emotion");
    await act(async () => {
      await save({ packs });
      await scanModels();
    });
  }
  async function connect() {
    await act(async () => {
      const r = await api<{ request_id: string; authorize_url: string }>(
        "/api/share/connect",
        { method: "POST" },
      );
      setConnection(r);
      setIdentity("yike");
    });
  }
  async function finish() {
    await act(async () => {
      const result = await api<{ route: string; state: SetupState }>(
        "/api/setup/complete",
        {
          method: "POST",
          body: JSON.stringify({
            mode: identity,
            privacy,
            manual,
            policy_version: state.policy_version,
          }),
        },
      );
      onComplete(result.state, result.route);
    });
  }

  useEffect(() => {
    let active = true;
    Promise.all([
      api<Catalog>("/api/setup/catalog"),
      api<ShareStatus>("/api/share/status"),
      api<Documents>("/api/setup/documents"),
    ])
      .then(([c, a, d]) => {
        if (active) {
          setCatalog(c);
          setAccount(a);
          setDocuments(d);
        }
      })
      .catch((e) => active && setError(message(e)));
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<SetupState>("/api/setup");
        if (!active) return;
        setState(next);
        const c = await api<ComfyState>("/api/comfy");
        if (active) setComfy(c);
      } catch (e) {
        if (active) setError(message(e));
      }
      if (active) timer = setTimeout(poll, 1500);
    }
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    if (step === "comfy" && !scanned && !scanning) void scanComfy();
    if (step === "models") void scanModels().catch((e) => setError(message(e)));
    if (step === "verify") void checkReady().catch((e) => setError(message(e)));
  }, [step, scanned, scanning, scanModels, checkReady]);
  useEffect(() => {
    const j = state.job;
    if (
      !j ||
      ["queued", "running"].includes(j.status) ||
      lastJob.current === j.id
    )
      return;
    lastJob.current = j.id;
    void scanModels().catch(() => {});
    void checkReady().catch(() => {});
  }, [state.job, scanModels, checkReady]);
  useEffect(() => {
    if (!connection) return;
    let active = true;
    const timer = setInterval(async () => {
      try {
        const r = await api<{ state: string; error?: string }>(
          `/api/share/connect/${connection.request_id}`,
        );
        if (!active) return;
        if (r.state === "approved") {
          setAccount(await api<ShareStatus>("/api/share/status"));
          setConnection(null);
        } else if (r.state !== "pending") {
          setError(r.error || "授权已过期，请重新连接。");
          setConnection(null);
        }
      } catch (e) {
        if (active) setError(message(e));
      }
    }, 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [connection]);
  useEffect(() => {
    const focus = () => {
      void refreshComfy().catch((e) => setError(message(e)));
      void api<ShareStatus>("/api/share/status")
        .then(setAccount)
        .catch(() => {});
    };
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, [refreshComfy]);
  useEffect(() => {
    if (comfy && !portInitialized.current) {
      setPort(comfy.port);
      portInitialized.current = true;
    }
  }, [comfy]);
  useEffect(() => {
    if (
      step === "models" &&
      !state.share_scan &&
      !busy &&
      !shareAttempted.current
    ) {
      shareAttempted.current = true;
      void job("share");
    }
  }, [step, state.share_scan, busy]);
  const selectedFiles =
    catalog?.files.filter((f) =>
      f.packs.some((p) => state.packs.includes(p)),
    ) || [];
  const bytes = selectedFiles.reduce((sum, f) => sum + f.size, 0),
    jobRunning =
      !!state.job && ["queued", "running"].includes(state.job.status);
  const validationReady =
    state.packs.length === 0 ||
    (!!state.validation && !state.validation.missing.length);
  const canNext =
    step === "welcome" ||
    (step === "comfy" &&
      ["running", "external"].includes(comfy?.status || "")) ||
    (step === "models" && state.packs.length > 0) ||
    (step === "verify" && validationReady && !!readiness?.ready);
  const missing =
    state.validation?.missing || files.filter((f) => f.status !== "unverified");
  const iconFor = (id: string) =>
    id.includes("indextts") ? (
      <AudioLines size={20} />
    ) : id.includes("video") ||
      id.includes("turbo") ||
      id.includes("latentsync") ? (
      <Film size={20} />
    ) : (
      <Image size={20} />
    );
  return {
    state,
    catalog,
    error,
    setError,
    acting,
    comfy,
    candidates,
    scanned,
    scanning,
    installPath,
    setInstallPath,
    manualPath,
    setManualPath,
    port,
    setPort,
    modelPath,
    setModelPath,
    files,
    modelScan,
    readiness,
    picker,
    setPicker,
    copyDone,
    setCopyDone,
    showMissing,
    setShowMissing,
    identity,
    setIdentity,
    account,
    connection,
    setConnection,
    privacy,
    setPrivacy,
    manual,
    setManual,
    document,
    setDocument,
    documents,
    mainRef,
    step,
    index,
    busy,
    refresh,
    refreshComfy,
    scanModels,
    checkReady,
    act,
    save,
    go,
    job,
    useExistingModels,
    scanComfy,
    selectComfy,
    chooseDirectory,
    baseOnly,
    togglePack,
    connect,
    finish,
    selectedFiles,
    bytes,
    jobRunning,
    validationReady,
    canNext,
    missing,
    iconFor,
  };
}
export type OnboardingView = ReturnType<typeof useOnboarding>;
