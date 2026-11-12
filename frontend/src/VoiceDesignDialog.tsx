import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AudioLines, LoaderCircle } from "lucide-react";
import { api, jsonBody, mediaUrl } from "./api";
import { Modal } from "./ui";
import { activeGenerationStates, generationStateLabels } from "./generationTypes";
import type { GenerationJob } from "./generationTypes";
import type { SubjectSnapshot } from "./subjectTypes";
import "./voice-design.css";

const PROFILE = "builtin-h3-voice-design-local";
const DEFAULT_TEXT = "你好，很高兴认识你。今天的天气很好，我们一起出去走走吧。";
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
type Profile = { ready: boolean; errors: string[] };

export default function VoiceDesignDialog({ projectId, subjectId, subject, onClose, onAdopt, onBeforeSubmit }: {
  projectId: string; subjectId: string; subject: SubjectSnapshot;
  onClose: () => void; onAdopt: (voice: Pick<SubjectSnapshot, "voice_version_id" | "voice_name" | "voice_transcript">) => void;
  onBeforeSubmit: () => Promise<void>;
}) {
  const [description, setDescription] = useState("");
  const [text, setText] = useState(DEFAULT_TEXT);
  const [usePortrait, setUsePortrait] = useState(false);
  const [count, setCount] = useState(1);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [jobs, setJobs] = useState<GenerationJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const alive = useRef(true);
  const attempts = useRef<{ fingerprint: string; ids: string[] } | null>(null);
  useEffect(() => {
    alive.current = true;
    let polling = false;
    const refresh = async () => {
      if (polling) return;
      polling = true;
      try {
        const response = await api<{ items: GenerationJob[] }>(`/api/generations?project_id=${encodeURIComponent(projectId)}&limit=500`);
        if (alive.current) setJobs(response.items.filter(job => job.request?.workflow_id === PROFILE && job.request?.subject_node_id === subjectId));
      } catch (caught) { if (alive.current) setError(message(caught)); }
      finally { polling = false; }
    };
    api<Profile>("/api/voice-design/settings").then(value => { if (alive.current) setProfile(value); }).catch(caught => { if (alive.current) setError(message(caught)); });
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { alive.current = false; window.clearInterval(timer); };
  }, [projectId, subjectId]);

  const generate = async () => {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError("");
    const body = { kind: "audio", project_id: projectId, subject_node_id: subjectId, workflow_id: PROFILE,
      prompt: text.trim(), voice_design_options: { description: description.trim() }, parameters: { seed: -1 },
      references: usePortrait && subject.image_version_ids[0] ? [{ version_id: subject.image_version_ids[0] }] : [] };
    const fingerprint = jsonBody({ body, count });
    if (attempts.current?.fingerprint !== fingerprint) attempts.current = { fingerprint, ids: Array.from({ length: count }, () => crypto.randomUUID()) };
    try {
      await onBeforeSubmit();
      // Keep request IDs after a connection failure: retry cannot duplicate accepted jobs.
      for (const id of attempts.current.ids) {
        const job = await api<GenerationJob>("/api/generations", { method: "POST", headers: { "X-Request-ID": id }, body: jsonBody(body) });
        if (alive.current) setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
      }
      attempts.current = null;
    } catch (caught) { if (alive.current) setError(message(caught)); }
    finally { submitting.current = false; if (alive.current) setBusy(false); }
  };
  const running = jobs.some(job => activeGenerationStates.has(job.status));
  return createPortal(<Modal title={`${subject.name || "角色"} · 设计专属音色`} wide className="voice-design-modal" onClose={() => { if (!submitting.current) onClose(); }}>
    <div className="voice-design">
      <p>用文字设计声线，无需已有录音。试听满意后绑定角色，后续原生音画只参考声线，按镜头重新演绎。</p>
      <label>声线描述<textarea aria-label="声线描述" rows={3} maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} placeholder="例如：二十多岁女性，中音偏低，温润清澈，带少量气声，普通话自然，辨识度来自柔和鼻腔共鸣。避免写当前剧情情绪。" /></label>
      <label>中性试听文本<textarea aria-label="中性试听文本" rows={2} minLength={4} maxLength={50} value={text} onChange={event => setText(event.target.value)} /></label>
      <div className="voice-design-options">
        <label>候选数量<select aria-label="音色候选数量" value={count} onChange={event => setCount(Number(event.target.value))}><option value={1}>1 个</option><option value={3}>3 个</option></select></label>
        {subject.image_version_ids.length > 0 && <label><input type="checkbox" checked={usePortrait} onChange={event => setUsePortrait(event.target.checked)} />参考角色外形</label>}
        <button className="button primary" disabled={busy || running || !profile?.ready || !description.trim() || text.trim().length < 4} onClick={() => void generate()}>{busy ? <LoaderCircle size={15} className="spin" /> : <AudioLines size={15} />}生成音色候选</button>
      </div>
      <small>候选自动保存到资产库，可在这里试听和绑定。关闭窗口后任务继续。每段试听约 8 秒，生成耗时接近原生视频采样。跨镜头的音色一致性仍需试听确认。</small>
      {profile && !profile.ready && <div role="alert" className="voice-design-error">{profile.errors.join("；")}</div>}
      {error && <div role="alert" className="voice-design-error">{error}</div>}
      <div className="voice-design-candidates" aria-label="音色候选">
        {!jobs.length && <p>生成后在这里试听，采用前会保留角色当前音色。</p>}
        {jobs.map((job, index) => {
          const version = job.outputs[0]?.version_id;
          const bound = !!version && version === subject.voice_version_id;
          const options = job.request?.voice_design_options as { description?: string } | undefined;
          return <article key={job.id}>
            <header><strong>候选 {jobs.length - index}</strong><span>{generationStateLabels[job.status]}</span></header>
            <p>{options?.description}</p>
            {activeGenerationStates.has(job.status) && <small>{job.execution_progress?.label || job.message}{typeof job.execution_progress?.value === "number" && job.execution_progress?.max ? ` · ${job.execution_progress.value} / ${job.execution_progress.max}` : ""}</small>}
            {version && <audio controls preload="none" aria-label={`试听音色候选 ${jobs.length - index}`} src={mediaUrl(version, "preview")} onPlay={event => { const playing = event.currentTarget; playing.closest(".voice-design-candidates")?.querySelectorAll("audio").forEach(audio => { if (audio !== playing) audio.pause(); }); }} />}
            {job.status === "failed" && <p role="alert">{typeof job.error === "string" ? job.error : job.error?.message || "生成失败，请重新生成。"}</p>}
            {job.status === "succeeded" && version && <button className="button primary" disabled={bound} onClick={() => onAdopt({ voice_version_id: version, voice_name: `${subject.name || "角色"} · 专属音色`, voice_transcript: String(job.request?.dialogue_text || job.request?.prompt || "") })}>{bound ? "当前角色音色" : "采用并绑定角色"}</button>}
          </article>;
        })}
      </div>
    </div>
  </Modal>, document.body);
}
