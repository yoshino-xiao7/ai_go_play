// Opening titles: an aperture iris opens on the studio once per browser session.
// Click or any key skips it; reduced motion never shows it.
import { useEffect, useState } from "react";
import { motionReduced } from "../design/appearance";

const key = "manju:boot-iris";
const BLADES = 8;

function seen() {
  try { return sessionStorage.getItem(key) === "1"; } catch { return true; }
}

export default function BootIris() {
  const [phase, setPhase] = useState<"show" | "open" | "gone">(() => (seen() || motionReduced() ? "gone" : "show"));
  useEffect(() => {
    if (phase === "gone") return;
    try { sessionStorage.setItem(key, "1"); } catch { /* optional */ }
    const open = window.setTimeout(() => setPhase("open"), 900);
    const gone = window.setTimeout(() => setPhase("gone"), 1900);
    const skip = () => setPhase("gone");
    window.addEventListener("keydown", skip, { once: true });
    return () => { window.clearTimeout(open); window.clearTimeout(gone); window.removeEventListener("keydown", skip); };
  }, [phase === "gone"]); // eslint-disable-line react-hooks/exhaustive-deps
  if (phase === "gone") return null;
  return (
    <div className={`boot-iris is-${phase}`} onClick={() => setPhase("gone")} aria-hidden="true">
      <svg className="boot-blades" viewBox="-100 -100 200 200">
        <defs>
          <linearGradient id="boot-g" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stopColor="var(--accent-hover)" /><stop offset="0.35" stopColor="var(--accent)" />
            <stop offset="0.65" stopColor="var(--accent-deep)" /><stop offset="1" stopColor="var(--accent-deep)" />
          </linearGradient>
        </defs>
        {Array.from({ length: BLADES }, (_, i) => (
          <g key={i} transform={`rotate(${(360 / BLADES) * i})`}>
            <path className="boot-blade" style={{ "--i": i } as React.CSSProperties} d="M0 0 L96 -38 A104 104 0 0 1 96 38 Z" />
          </g>
        ))}
        <circle className="boot-ring" r="98" fill="none" stroke="url(#boot-g)" strokeWidth="1.2" />
      </svg>
      <div className="boot-mark">
        <span className="boot-word">ai_go_play</span>
        <small>Local Reel Studio · 本地影视工作台</small>
      </div>
    </div>
  );
}
