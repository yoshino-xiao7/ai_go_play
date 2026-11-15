import { useEffect, useState } from "react";
import {
  ArrowUp,
  Folder,
  FolderOpen,
  HardDrive,
  LoaderCircle,
} from "lucide-react";
import { api } from "../api";
import { Modal } from "../ui";

type Listing = {
  path: string | null;
  parent: string | null;
  directories: { name: string; path: string }[];
};
export default function DirectoryPicker({
  title,
  onSelect,
  onClose,
}: {
  title: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}) {
  const [listing, setListing] = useState<Listing | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function open(path?: string) {
    setBusy(true);
    setError("");
    try {
      setListing(
        await api<Listing>(
          "/api/setup/directories" +
            (path ? "?path=" + encodeURIComponent(path) : ""),
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void open();
  }, []);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="setup-folder-browser">
        <div className="setup-folder-toolbar">
          <button aria-label="返回常用位置" onClick={() => void open()}>
            <HardDrive size={18} />
          </button>
          <button
            disabled={!listing?.parent || busy}
            aria-label="上一级目录"
            onClick={() => void open(listing?.parent || undefined)}
          >
            <ArrowUp size={18} />
          </button>
          <span>{listing?.path || "常用位置与磁盘"}</span>
        </div>
        {error && (
          <p role="alert" className="setup-error">
            {error}
          </p>
        )}
        <div className="setup-folder-list" aria-busy={busy}>
          {busy ? (
            <LoaderCircle className="setup-spin" />
          ) : (
            listing?.directories.map((dir) => (
              <button key={dir.path} onClick={() => void open(dir.path)}>
                <Folder size={18} />
                <span>{dir.name}</span>
              </button>
            ))
          )}
          {!busy && listing?.path && !listing.directories.length && (
            <p>这个目录没有子文件夹，可以直接选择。</p>
          )}
        </div>
        <button
          className="btn setup-primary"
          disabled={!listing?.path || busy}
          onClick={() => listing?.path && onSelect(listing.path)}
        >
          <FolderOpen size={17} />
          使用这个目录
        </button>
      </div>
    </Modal>
  );
}
