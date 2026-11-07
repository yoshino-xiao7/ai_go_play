import type { Edge, Node } from "@xyflow/react";
import type { GenerationDraft, ImageReference } from "./generationTypes";
import type { SubjectSnapshot } from "./subjectTypes";

export type ReferenceNode = Node<{kind?: string; title?: string; locked?: boolean; asset_version_id?: string; subject?: SubjectSnapshot; generation?: GenerationDraft} & Record<string, unknown>>;
export const edgeRole = (edge: Edge) => String(edge.data?.role || "pending");
export const edgeLocked = (edge: Edge, nodes: ReferenceNode[]) => nodes.some(node => (node.id === edge.source || node.id === edge.target) && node.data.locked);
export const canReference = (source?: ReferenceNode, target?: ReferenceNode) => target?.data.generation?.workflow_id === "builtin-latentsync15-local" ? !!(target.type === "media" && source?.type === "media" && ["video","audio"].includes(source.data.kind||"") && (source.data.asset_version_id || source.data.generation)) : target?.data.kind === "audio" ? !!(source?.type === "subject" ? source.data.subject?.voice_version_id : source?.data.kind === "audio" && (source.data.asset_version_id || source.data.generation)) && target.type === "media" : !!(source?.data.asset_version_id || source?.data.generation) && target?.type === "media" && (target.data.kind === "video" && (source!.type === "subject" || source!.type === "media" && ["image","video","audio"].includes(source!.data.kind||"")) || target.data.kind === "image" && (source!.type === "subject" || source!.type === "media" && source!.data.kind === "image"));

export function reconcileReferences<T extends ReferenceNode>(nodes: T[], edges: Edge[]): T[] {
  const nodesById = new Map(nodes.map(node => [node.id, node]));
  const incomingByTarget = new Map<string, Edge[]>();
  for (const edge of edges) {
    if (edgeRole(edge) !== "reference") continue;
    const incoming = incomingByTarget.get(edge.target) || [];
    incoming.push(edge);
    incomingByTarget.set(edge.target, incoming);
  }
  return nodes.map(node => {
    const draft = node.data.generation;
    const incoming = incomingByTarget.get(node.id) || [];
    if (!draft && !incoming.length) return node;
    let refs = (draft?.references || []).flatMap(ref => {
      if (ref.source !== "connection" || incoming.some(edge => edge.id === ref.edge_id)) return [ref];
      // Deleting a source placement preserves its immutable input; deleting a line removes it.
      return ref.node_id && !nodesById.has(ref.node_id) ? [{...ref, source:"mention" as const, edge_id:undefined}] : [];
    });
    for (const edge of incoming) {
      if (refs.some(ref => ref.edge_id === edge.id || draft?.workflow_id === "builtin-latentsync15-local" && ref.node_id === edge.source)) continue;
      const source = nodesById.get(edge.source);
      if (!canReference(source,node)) continue;
      const subject=source!.data.subject;
      // A configured but unfinished source is a DAG dependency. Pin its version
      // only after an output exists; the scheduler resolves the typed edge.
      if (!(node.data.kind === "audio" && subject ? subject.voice_version_id : source!.data.asset_version_id)) continue;
      const baseTitle=subject?.name || source!.data.title || "参考图片";
      let title=baseTitle, suffix=2;
      while(refs.some(ref=>ref.title===title)) title=baseTitle+" · "+suffix++;
      const ref: ImageReference = {id:`edge-${edge.id}`, version_id:(node.data.kind==="audio" && subject ? subject.voice_version_id : source!.data.asset_version_id)!, node_id:source!.id, title, description:subject?.description || "", use_description:true, source:"connection", edge_id:edge.id, ...(node.data.kind==="audio"?{media_type:"audio" as const}:{}),...(node.data.kind==="video"?{media_type:(source!.data.kind||"image") as "image"|"video"|"audio",role:draft?.workflow_id==="builtin-latentsync15-local"?(source!.data.kind as "video"|"audio"):draft?.video_mode==="frames"?(refs.some(item=>item.role==="first_frame")?"last_frame" as const:"first_frame" as const):"reference" as const}:{})};
      refs=[...refs,ref];
    }
    if (draft && JSON.stringify(refs) === JSON.stringify(draft.references)) return node;
    return {...node,data:{...node.data,generation:{mode:"text_to_image",prompt:"",parameters:{},...(node.data.kind==="audio"?{kind:"audio" as const,workflow_id:"builtin-indextts25-local"}:{}),...(node.data.kind==="video"?{kind:"video" as const,video_mode:"reference" as const,workflow_id:"builtin-h3-local"}:{}),...draft,references:refs}}};
  });
}
