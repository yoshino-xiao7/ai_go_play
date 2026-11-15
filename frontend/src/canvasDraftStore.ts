// Canvas documents can be much larger than Web Storage's per-origin quota.
// Keep structured data in IndexedDB; migrate legacy drafts only after commit.
const databaseName = "manju-canvas-drafts";
const storeName = "drafts";
let opening: Promise<IDBDatabase> | undefined;
const pending = new Map<string, Promise<unknown>>();

function database(): Promise<IDBDatabase> {
  if (!opening) {
    opening = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(storeName);
      request.onsuccess = () => {
        const db = request.result;
        db.onversionchange = () => { db.close(); opening = undefined; };
        resolve(db);
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("草稿数据库正在升级，请关闭旧版页面后重试。"));
    }).catch(error => { opening = undefined; throw error; });
  }
  return opening;
}

async function transaction<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const request = action(tx.objectStore(storeName));
    tx.oncomplete = () => resolve(request.result);
    tx.onabort = () => reject(tx.error || request.error || new Error("草稿存储事务未完成。"));
    tx.onerror = () => reject(tx.error || request.error);
  });
}

function ordered<T>(key: string, action: () => Promise<T>): Promise<T> {
  const result = (pending.get(key) || Promise.resolve()).catch(() => {}).then(action);
  pending.set(key, result);
  void result.finally(() => { if (pending.get(key) === result) pending.delete(key); }).catch(() => {});
  return result;
}

function legacyValue(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export function writeCanvasDraft(key: string, document: unknown): Promise<void> {
  return ordered(key, async () => {
    const legacy = legacyValue(key);
    await transaction("readwrite", store => store.put(document, key));
    // This key belongs to this editor session. Other sessions and backups stay.
    try { if (legacyValue(key) === legacy) localStorage.removeItem(key); } catch { /* Duplicate legacy copy is safe. */ }
  });
}

async function migrate<T>(key: string, legacy: T): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readwrite");
    const store = tx.objectStore(storeName);
    const get = store.get(key);
    let chosen = legacy;
    get.onsuccess = () => {
      const current = get.result;
      const savedAt = (value: unknown) => Number((value as { saved_at?: number })?.saved_at) || 0;
      chosen = current && savedAt(current) >= savedAt(legacy) ? current : legacy;
      try { store.put(chosen, key); } catch { tx.abort(); }
    };
    tx.oncomplete = () => resolve(chosen);
    tx.onabort = () => reject(tx.error || new Error("旧草稿迁移未完成。"));
    tx.onerror = () => reject(tx.error);
  });
}

export function readCanvasDraft<T = unknown>(key: string): Promise<T | undefined> {
  return ordered(key, async () => {
    const raw = legacyValue(key);
    if (!raw) return transaction("readonly", store => store.get(key));
    const legacy = JSON.parse(raw) as T;
    try {
      const chosen = await migrate(key, legacy);
      try { if (legacyValue(key) === raw) localStorage.removeItem(key); } catch { /* The committed copy remains authoritative. */ }
      return chosen;
    } catch { return legacy; } // Never discard the original on migration failure.
  });
}

export function removeCanvasDraft(key: string): Promise<void> {
  return ordered(key, async () => {
    await transaction("readwrite", store => store.delete(key));
    try { localStorage.removeItem(key); } catch { /* Keep an extra copy if necessary. */ }
  });
}

export async function listCanvasDrafts<T = unknown>(prefix: string): Promise<{ key: string; document: T }[]> {
  const matches = (key: string) => key === prefix || key.startsWith(prefix + ":");
  const keys = new Set<string>();
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && matches(key)) keys.add(key);
    }
  } catch { /* IndexedDB may still be available. */ }
  try {
    const stored = await transaction("readonly", store => store.getAllKeys(IDBKeyRange.bound(prefix, prefix + "\uffff")));
    for (const key of stored) if (typeof key === "string" && matches(key)) keys.add(key);
  } catch (error) { if (!keys.size) throw error; }
  const entries = await Promise.all([...keys].map(async (key): Promise<{ key: string; document: T } | null> => {
    try { const document = await readCanvasDraft<T>(key); return document ? { key, document } : null; }
    catch { return null; } // One malformed old draft must not hide the others.
  }));
  return entries.filter((entry): entry is { key: string; document: T } => entry !== null);
}
