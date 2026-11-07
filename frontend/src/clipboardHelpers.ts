import type { Edge, Node } from "@xyflow/react";

export type ClipboardSnapshot = { nodes: Node[]; edges: Edge[] };
export type CanvasClipboardPayload =
  | { kind: "canvas"; snapshot: ClipboardSnapshot }
  | { kind: "text"; text: string }
  | { kind: "files"; files: File[] };

export function parseClipboardText(
  text: string,
): CanvasClipboardPayload | null {
  if (!text) return null;
  try {
    const value = JSON.parse(text);
    if (
      value?.manju_canvas === 1 &&
      Array.isArray(value.nodes) &&
      value.nodes.length &&
      Array.isArray(value.edges) &&
      value.nodes.every(
        (node: Node) =>
          typeof node?.id === "string" &&
          node.data &&
          typeof node.data === "object" &&
          Number.isFinite(node.position?.x) &&
          Number.isFinite(node.position?.y),
      ) &&
      value.edges.every(
        (edge: Edge) =>
          typeof edge?.id === "string" &&
          typeof edge.source === "string" &&
          typeof edge.target === "string",
      )
    )
      return {
        kind: "canvas",
        snapshot: { nodes: value.nodes, edges: value.edges },
      };
  } catch {
    /* Ordinary text is also a supported canvas paste. */
  }
  return { kind: "text", text };
}

export async function readCanvasClipboard(
  fallback: ClipboardSnapshot | null,
): Promise<{
  payload: CanvasClipboardPayload | null;
  error?: "denied" | "unsupported";
}> {
  try {
    if (navigator.clipboard?.read) {
      const items = await navigator.clipboard.read();
      let text = "";
      const files: File[] = [];
      for (const item of items) {
        if (item.types.includes("text/plain"))
          text = await (await item.getType("text/plain")).text();
        const imageType = item.types.find((type) => type.startsWith("image/"));
        if (imageType)
          files.push(
            new File(
              [await item.getType(imageType)],
              `剪贴板图片-${Date.now()}.${imageType.split("/")[1] || "png"}`,
              { type: imageType },
            ),
          );
      }
      const parsed = parseClipboardText(text);
      return {
        payload:
          parsed?.kind === "canvas"
            ? parsed
            : files.length
              ? { kind: "files", files }
              : parsed,
      };
    }
    if (navigator.clipboard?.readText)
      return {
        payload: parseClipboardText(await navigator.clipboard.readText()),
      };
  } catch {
    // Denied/unavailable system clipboard falls back to a canvas copy from this tab.
    return {
      payload: fallback?.nodes.length
        ? { kind: "canvas", snapshot: fallback }
        : null,
      error: "denied",
    };
  }
  return {
    payload: fallback?.nodes.length
      ? { kind: "canvas", snapshot: fallback }
      : null,
    error: "unsupported",
  };
}
