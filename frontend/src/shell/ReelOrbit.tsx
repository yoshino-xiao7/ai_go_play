// The projects hero centrepiece: recent projects as frames on a slowly turning 3D reel.
// Drag to spin (with inertia), hover to pause, click the front frame to open it.
import { useEffect, useRef } from "react";
import { Layers2 } from "lucide-react";
import { mediaUrl } from "../api";
import type { Project } from "../types";
import { motionReduced } from "../design/appearance";

const FRAMES = 8;
const DRAG_SLOP = 6;

export default function ReelOrbit({ projects, onOpen }: { projects: Project[]; onOpen: (id: string) => void }) {
  const ringRef = useRef<HTMLDivElement>(null);
  // A press only becomes a drag (and captures the pointer) after DRAG_SLOP px; a short press opens
  // the frame it started on. Capturing on pointerdown would retarget pointerup/click to .orbit.
  const motion = useRef({ angle: -12, velocity: 0, dragging: false, pressed: false, captured: false, hover: false, lastX: 0, moved: 0, frame: null as string | null });
  const recent = [...projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, FRAMES);
  const faces = Array.from({ length: FRAMES }, (_, i) => recent[i] || null);

  useEffect(() => {
    const ring = ringRef.current;
    if (!ring) return;
    const m = motion.current;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const dt = Math.min(48, now - last) / 16.67;
      last = now;
      if (!m.dragging) {
        const idle = m.hover || motionReduced() ? 0 : -0.12;
        m.velocity += (idle - m.velocity) * 0.035 * dt;
        m.angle += m.velocity * dt;
      }
      ring.style.setProperty("--a", `${m.angle.toFixed(2)}deg`);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const down = (event: React.PointerEvent) => {
    if (event.button !== 0) return;
    const m = motion.current;
    const frame = event.target instanceof Element ? event.target.closest<HTMLElement>(".orbit-frame:not(.is-blank)") : null;
    m.pressed = true; m.dragging = false; m.captured = false; m.lastX = event.clientX; m.moved = 0; m.frame = frame?.dataset.id || null;
  };
  const move = (event: React.PointerEvent) => {
    const m = motion.current;
    if (!m.pressed) return;
    const dx = event.clientX - m.lastX;
    m.lastX = event.clientX;
    m.moved += Math.abs(dx);
    if (!m.dragging && m.moved < DRAG_SLOP) return;
    if (!m.captured) {
      m.dragging = true; m.captured = true; m.velocity = 0;
      try { (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); } catch { /* pointer already gone */ }
    }
    m.angle += dx * 0.35;
    m.velocity = dx * 0.35;
  };
  const up = (event?: React.PointerEvent) => {
    const m = motion.current;
    const open = m.pressed && !m.dragging && m.frame && event?.type === "pointerup" ? m.frame : null;
    m.pressed = false; m.dragging = false; m.captured = false; m.frame = null;
    if (open) onOpen(open);
  };

  return (
    <div className="orbit" onPointerEnter={() => { motion.current.hover = true; }} onPointerLeave={() => { motion.current.hover = false; if (!motion.current.captured) up(); }}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} aria-label="最近项目胶卷">
      <div className="orbit-halo" aria-hidden="true" />
      <div className="orbit-ring" ref={ringRef}>
        {faces.map((project, i) => (
          <button key={project?.id || `blank-${i}`} className={`orbit-frame ${project ? "" : "is-blank"}`} style={{ "--k": i } as React.CSSProperties}
            tabIndex={project ? 0 : -1} aria-hidden={project ? undefined : true} aria-label={project ? `打开 ${project.name}` : undefined}
            data-id={project?.id}
            // Pointer presses open on pointerup (see up()); click with detail 0 is the keyboard (Enter/Space).
            onClick={event => { if (project && event.detail === 0) onOpen(project.id); }}>
            <span className="orbit-film" aria-hidden="true" />
            {project?.cover_version_id
              ? <img src={mediaUrl(project.cover_version_id)} alt="" draggable={false} onError={event => { event.currentTarget.hidden = true; }} />
              : <span className="orbit-blank"><Layers2 size={26} strokeWidth={1.2} /></span>}
            {project && <span className="orbit-name">{project.name}</span>}
          </button>
        ))}
      </div>
      <div className="orbit-floor" aria-hidden="true" />
    </div>
  );
}
