import { Fragment, useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { BookOpen, FileText, List, LoaderCircle, Pencil, Plus, Save, Trash2 } from "lucide-react";
import { api, ApiError, jsonBody } from "./api";
import { EmptyState, Modal } from "./ui";
import "./screenplay.css";

type Character = { name: string; bio: string };
type Episode = { id: string; title: string; outline: string; script: string };
type Screenplay = {
  title: string;
  audience: string;
  hooks: string;
  genre: string;
  logline: string;
  synopsis: string;
  characters: Character[];
  episodes: Episode[];
};
type Snapshot = { revision: number; document: Screenplay | null };
type Tab = "story" | "outline" | "script";
type Props = { projectId: string; onClose: () => void };

const tabs = [
  { id: "story", label: "故事设定", icon: BookOpen },
  { id: "outline", label: "分集大纲", icon: List },
  { id: "script", label: "剧本正文", icon: FileText },
] as const;
const storyFields = [
  { key: "title", label: "剧本名称" },
  { key: "audience", label: "目标受众" },
  { key: "hooks", label: "核心梗" },
  { key: "genre", label: "故事类型" },
  { key: "logline", label: "一句话故事", rows: 2 },
  { key: "synopsis", label: "故事梗概", rows: 7 },
] as const;
const blankScreenplay = (): Screenplay => ({
  title: "未命名剧本",
  audience: "",
  hooks: "",
  genre: "",
  logline: "",
  synopsis: "",
  characters: [],
  episodes: [],
});
const numberLabel = (index: number) => String(index + 1).padStart(2, "0");
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "本地服务暂时无法连接。";

function ScriptText({ text }: { text: string }) {
  const lines = text.split("\n");
  return lines.map((line, index) => {
    const heading = /^#{1,6}\s+(场.+)$/.exec(line);
    return (
      <Fragment key={index}>
        {heading ? <span className="screenplay-scene-heading" role="heading" aria-level={4}>{heading[1]}</span> : line}
        {index < lines.length - 1 ? "\n" : null}
      </Fragment>
    );
  });
}

function Field({ label, value, onChange, rows, disabled, className = "" }: {
  label: string; value: string; onChange: (value: string) => void; rows?: number; disabled: boolean; className?: string;
}) {
  return (
    <label className={`screenplay-field ${className}`}>
      <span>{label}</span>
      {rows
        ? <textarea rows={rows} value={value} disabled={disabled} onChange={event => onChange(event.target.value)} />
        : <input value={value} disabled={disabled} onChange={event => onChange(event.target.value)} />}
    </label>
  );
}

function StorySettings({ screenplay, editing, disabled, onChange }: {
  screenplay: Screenplay; editing: boolean; disabled: boolean; onChange: (next: Screenplay) => void;
}) {
  function updateCharacter(index: number, patch: Partial<Character>) {
    onChange({ ...screenplay, characters: screenplay.characters.map((character, position) => (
      index === position ? { ...character, ...patch } : character
    )) });
  }

  return (
    <div className="screenplay-story">
      <section aria-labelledby="screenplay-story-heading">
        <h3 id="screenplay-story-heading">故事设定</h3>
        {editing ? (
          <div className="screenplay-story-grid">
            {storyFields.map(field => (
              <Field key={field.key} label={field.label} value={screenplay[field.key]}
                rows={"rows" in field ? field.rows : undefined}
                className={"rows" in field ? "screenplay-span" : ""}
                disabled={disabled} onChange={value => onChange({ ...screenplay, [field.key]: value })} />
            ))}
          </div>
        ) : (
          <dl className="screenplay-story-grid">
            <div><dt>集数</dt><dd>{screenplay.episodes.length}</dd></div>
            {storyFields.filter(field => field.key !== "title").map(field => (
              <div className={"rows" in field ? "screenplay-span" : ""} key={field.key}>
                <dt>{field.label}</dt>
                <dd>{screenplay[field.key] || "—"}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      <section aria-labelledby="screenplay-characters-heading">
        <div className="screenplay-section-heading">
          <h3 id="screenplay-characters-heading">人物小传</h3>
          {editing && <button className="screenplay-button" disabled={disabled} onClick={() => onChange({
            ...screenplay, characters: [...screenplay.characters, { name: "未命名人物", bio: "" }],
          })}><Plus size={15} />添加人物</button>}
        </div>
        {!screenplay.characters.length && <p className="screenplay-muted">还没有人物小传。</p>}
        <div className="screenplay-characters">
          {screenplay.characters.map((character, index) => (
            <article className="screenplay-character" key={index}>
              {editing ? (
                <>
                  <div className="screenplay-character-heading">
                    <Field label="角色名" value={character.name} disabled={disabled} onChange={name => updateCharacter(index, { name })} />
                    <button className="screenplay-button screenplay-icon" aria-label={`删除人物 ${character.name}`}
                      disabled={disabled} onClick={() => onChange({
                        ...screenplay, characters: screenplay.characters.filter((_, position) => position !== index),
                      })}><Trash2 size={15} /></button>
                  </div>
                  <Field label="人物小传" value={character.bio} rows={6} disabled={disabled} onChange={bio => updateCharacter(index, { bio })} />
                </>
              ) : (
                <>
                  <h4>{character.name}</h4>
                  <div className="screenplay-copy">{character.bio || "—"}</div>
                </>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default function ScreenplayWorkspace({ projectId, onClose }: Props) {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [draft, setDraft] = useState<Screenplay | null>(null);
  const [tab, setTab] = useState<Tab>("story");
  const [episodeId, setEpisodeId] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const reader = useRef<HTMLDivElement>(null);
  const tabId = useId();
  const endpoint = `/api/projects/${encodeURIComponent(projectId)}/screenplay`;
  const screenplay = draft ?? snapshot?.document;
  const editing = draft !== null;
  const dirty = editing && draft !== snapshot?.document;
  const episodes = screenplay?.episodes ?? [];
  const episode = episodes.find(item => item.id === episodeId) ?? episodes[0];
  const episodeIndex = episode ? episodes.indexOf(episode) : -1;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setNotice("");
    void api<Snapshot>(endpoint, { signal: controller.signal }).then(result => {
      if (controller.signal.aborted) return;
      setSnapshot(result);
      setDraft(null);
      setConflict(false);
    }).catch(caught => {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [endpoint, refresh]);

  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = true;
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty]);

  useEffect(() => { if (reader.current) reader.current.scrollTop = 0; }, [tab, episode?.id]);

  function close() {
    if (!saving && (!dirty || window.confirm("有未保存的剧本修改，确定关闭？"))) onClose();
  }

  function cancelEdit() {
    if (dirty && !window.confirm("确定放弃这次未保存的修改？")) return;
    setDraft(null);
    setError("");
    setConflict(false);
  }

  function reload() {
    if (dirty && !window.confirm("载入最新版本后会放弃当前修改，确定继续？")) return;
    setRefresh(value => value + 1);
  }

  async function save() {
    if (!draft || !snapshot || saving || conflict) return;
    if (!draft.title.trim()) {
      setError("请填写剧本名称。");
      setTab("story");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await api<Snapshot>(endpoint, {
        method: "PUT",
        body: jsonBody({ revision: snapshot.revision, document: draft }),
      });
      setSnapshot(next);
      setDraft(null);
      setNotice("剧本已保存");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setConflict(true);
        setError("剧本已在其他位置更新。当前修改仍在编辑器里。");
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setSaving(false);
    }
  }

  function selectTab(key: Tab, event: KeyboardEvent<HTMLButtonElement>) {
    const index = tabs.findIndex(item => item.id === key);
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    setTab(tabs[next].id);
    document.getElementById(`${tabId}-${tabs[next].id}`)?.focus();
  }

  function addEpisode() {
    if (!draft) return;
    const item = { id: crypto.randomUUID(), title: "未命名分集", outline: "", script: "" };
    setDraft({ ...draft, episodes: [...draft.episodes, item] });
    setEpisodeId(item.id);
  }

  function updateEpisode(patch: Partial<Episode>) {
    if (!draft || !episode) return;
    setDraft({ ...draft, episodes: draft.episodes.map(item => item.id === episode.id ? { ...item, ...patch } : item) });
  }

  function removeEpisode() {
    if (!draft || !episode || !window.confirm(`从剧本移除「${episode.title}」及其大纲和正文？`)) return;
    const next = draft.episodes.filter(item => item.id !== episode.id);
    setDraft({ ...draft, episodes: next });
    setEpisodeId(next[Math.min(episodeIndex, next.length - 1)]?.id ?? "");
  }

  let body: ReactNode;
  if (loading) {
    body = <div className="screenplay-state" role="status"><LoaderCircle className="spin" size={22} />正在读取剧本</div>;
  } else if (!snapshot) {
    body = <EmptyState icon={<FileText size={24} />} title="无法读取剧本" description={error || "请检查本地服务。"}
      action={<button className="screenplay-button" onClick={reload}>重新读取</button>} />;
  } else if (!screenplay) {
    body = <EmptyState icon={<BookOpen size={24} />} title="这个项目还没有剧本" description="为当前项目记录故事设定、分集大纲和正文。"
      action={<button className="screenplay-button screenplay-primary" onClick={() => setDraft(blankScreenplay())}><Plus size={16} />新建剧本</button>} />;
  } else if (tab === "story") {
    body = <div className="screenplay-reader" ref={reader}>
      <StorySettings screenplay={screenplay} editing={editing} disabled={saving} onChange={setDraft} />
    </div>;
  } else {
    body = <div className="screenplay-episode-layout">
      <aside className="screenplay-episodes" aria-label="分集列表">
        <div className="screenplay-episode-list-heading">
          <span>分集 <strong>{episodes.length}</strong></span>
          {editing && <button className="screenplay-button screenplay-icon" aria-label="添加分集" title="添加分集"
            disabled={saving} onClick={addEpisode}><Plus size={16} /></button>}
        </div>
        <ol>
          {episodes.map((item, index) => (
            <li key={item.id}>
              <button type="button" aria-current={episode?.id === item.id ? "true" : undefined} onClick={() => setEpisodeId(item.id)}>
                <span>{numberLabel(index)}</span><strong>{item.title || "未命名分集"}</strong>
              </button>
            </li>
          ))}
        </ol>
      </aside>
      <div className="screenplay-reader" ref={reader}>
        {episode ? <article className="screenplay-episode">
          <header>
            <p className="screenplay-muted">第 {numberLabel(episodeIndex)} 集</p>
            {editing ? (
              <div className="screenplay-character-heading">
                <Field label="本集标题" value={episode.title} disabled={saving} onChange={title => updateEpisode({ title })} />
                <button className="screenplay-button screenplay-icon" aria-label="移除本集" title="移除本集" disabled={saving} onClick={removeEpisode}><Trash2 size={16} /></button>
              </div>
            ) : <h3>{episode.title || "未命名分集"}</h3>}
          </header>
          {editing
            ? <Field label={tab === "outline" ? "本集大纲" : "本集正文"} value={episode[tab]} disabled={saving}
              rows={tab === "outline" ? 12 : 19} onChange={value => updateEpisode({ [tab]: value })} />
            : episode[tab]
              ? <div className={`screenplay-copy screenplay-episode-text ${tab === "script" ? "screenplay-script-text" : ""}`}>
                  {tab === "script" ? <ScriptText text={episode.script} /> : episode.outline}
                </div>
              : <p className="screenplay-muted">本集还没有{tab === "outline" ? "大纲" : "正文"}。</p>}
        </article> : <EmptyState icon={<List size={24} />} title="还没有分集" description="添加一集后即可填写标题、大纲和正文。"
          action={<button className="screenplay-button" onClick={() => {
            if (draft) addEpisode();
            else setDraft(screenplay);
          }}>{editing ? "添加分集" : "编辑剧本"}</button>} />}
      </div>
    </div>;
  }

  return (
    <Modal title="剧本" className="screenplay-workspace" wide onClose={close}>
      {screenplay && !loading && <>
        <div className="screenplay-toolbar">
          <div className="screenplay-project-title">
            <h2>{screenplay.title || "未命名剧本"}</h2>
            <p>{episodes.length} 集 · {episodes.filter(item => item.script.trim()).length} 集已有正文</p>
          </div>
          <div className="screenplay-actions">
            <span role="status">{dirty ? "未保存" : notice}</span>
            {editing ? <>
              <button className="screenplay-button" disabled={saving} onClick={cancelEdit}>取消编辑</button>
              <button className="screenplay-button screenplay-primary" disabled={!dirty || saving || conflict} onClick={() => void save()}>
                {saving ? <LoaderCircle size={16} className="spin" /> : <Save size={16} />}
                {saving ? "正在保存" : "保存剧本"}
              </button>
            </> : <button className="screenplay-button" onClick={() => { setDraft(screenplay); setNotice(""); }}><Pencil size={16} />编辑剧本</button>}
          </div>
        </div>
        <div className="screenplay-tabs" role="tablist" aria-label="剧本内容">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button key={id} id={`${tabId}-${id}`} role="tab" aria-selected={tab === id} aria-controls={`${tabId}-content`}
              tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)} onKeyDown={event => selectTab(id, event)}>
              <Icon size={16} />{label}
            </button>
          ))}
        </div>
      </>}
      {snapshot && error && !loading && <div className="screenplay-error" role="alert">
        <span>{error}</span>
        {conflict && <button className="screenplay-button" onClick={reload}>重新载入最新版本</button>}
      </div>}
      <div className="screenplay-content" id={`${tabId}-content`} role={screenplay && !loading ? "tabpanel" : undefined}
        aria-labelledby={screenplay && !loading ? `${tabId}-${tab}` : undefined}>{body}</div>
    </Modal>
  );
}
