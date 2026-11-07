import type { Asset } from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "string"
        ? detail
        : (detail as { message?: string })?.message;
    super(message || `请求失败（${status}）`);
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, body.detail ?? body);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const jsonBody = (body: unknown) => JSON.stringify(body);
export const mediaUrl = (
  versionId: string,
  variant = "thumbnail",
  download = false,
) =>
  `/api/media/${encodeURIComponent(versionId)}?variant=${encodeURIComponent(variant)}${download ? "&download=true" : ""}`;

export function uploadAsset(
  file: File,
  options: {
    projectId?: string;
    assetId?: string;
    onProgress?: (percent: number) => void;
  } = {},
): Promise<Asset> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    data.append("file", file);
    if (options.projectId) data.append("project_id", options.projectId);
    if (options.assetId) data.append("asset_id", options.assetId);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/assets/upload");
    xhr.setRequestHeader("X-Request-ID", crypto.randomUUID());
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable)
        options.onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => reject(new Error("连接中断，请检查本机服务后重试"));
    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error("服务返回了无法读取的数据"));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Asset);
      else reject(new ApiError(xhr.status, body.detail ?? body));
    };
    xhr.send(data);
  });
}

export function sizeText(bytes: number): string {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

export function dateText(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
}
