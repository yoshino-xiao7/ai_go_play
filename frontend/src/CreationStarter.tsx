import { useState } from "react";
import { Clapperboard, Image as ImageIcon, PenLine } from "lucide-react";
import { api } from "./api";
import type { Project } from "./types";
import { setDraftIntent } from "./draftIntent";
import StudioSelect from "./StudioSelect";

/**
 * Project page: start from one sentence. Opens the chosen (or a new) project's canvas with a new
 * image / video card holding this description. It never submits a generation by itself.
 */
export default function CreationStarter({ projects, onOpen, notify }: {
  projects: Project[];
  onOpen: (projectId: string) => void;
  notify: (message: string, error?: boolean) => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState<"image" | "video">("image");
  const [target, setTarget] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const recent = [...projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const chosen = target || recent[0]?.id || "new";
  const chosenName = chosen === "new" ? "新项目" : recent.find(item => item.id === chosen)?.name || "项目";
  const start = async () => {
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      let projectId = chosen;
      if (chosen === "new") {
        const name = text.replace(/\s+/g, " ").slice(0, 18) + (text.length > 18 ? "…" : "");
        projectId = (await api<Project>("/api/projects", { method: "POST", body: JSON.stringify({ name, aspect_ratio: "16:9" }) })).id;
      }
      setDraftIntent({ projectId, kind, prompt: text });
      onOpen(projectId);
    } catch (error) {
      notify((error as Error).message, true);
    } finally { setBusy(false); }
  };
  return (
    <section className="creation-start" aria-label="从一句描述开始">
      <div className="cs-head">
        <span className="cs-eyebrow"><PenLine size={13} />从一句描述开始</span>
        <div className="cs-kind" role="radiogroup" aria-label="创作类型">
          <button role="radio" aria-checked={kind === "image"} onClick={() => setKind("image")}><ImageIcon size={14} />图像</button>
          <button role="radio" aria-checked={kind === "video"} onClick={() => setKind("video")}><Clapperboard size={14} />视频</button>
        </div>
      </div>
      <textarea className="cs-prompt" value={prompt} rows={2} maxLength={4000} aria-label="画面描述"
        placeholder={kind === "image" ? "写一句画面：谁、在哪、光线与情绪…" : "写一句运动：镜头怎么动、谁在动…"}
        onChange={event => setPrompt(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void start(); } }} />
      <div className="cs-foot">
        <label className="cs-target">
          <span>放到</span>
          <StudioSelect aria-label="目标项目" value={chosen} onChange={event => setTarget(event.target.value)}>
            {recent.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            <option value="new">＋ 新建项目</option>
          </StudioSelect>
        </label>
        <span className="cs-hint">会在「{chosenName}」的画布新建一张{kind === "image" ? "图片" : "视频"}卡片，结果回到这张卡片；生成前还能加参考、改参数。</span>
        <button className="cs-go" disabled={!prompt.trim() || busy} onClick={() => void start()}>{busy ? "正在打开…" : "去画布起草"}</button>
      </div>
    </section>
  );
}
