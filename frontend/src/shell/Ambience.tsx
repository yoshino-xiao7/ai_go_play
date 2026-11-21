// Prism ambience: a full-screen WebGL aurora behind the whole studio.
// Domain-warped noise lit with the studio spectrum; it leans toward the cursor and calms down
// on the canvas (where the work, not the background, should move). It renders at reduced
// resolution, caps its frame rate, pauses in hidden tabs and freezes to a single frame when
// motion is reduced. Without WebGL the CSS fallback gradient in shell.css shows instead.
import { useEffect, useRef } from "react";
import { usePalette, useMotionReduced } from "../design/appearance";

const VERT = `attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`;
const FRAG = `
precision mediump float;
uniform vec2 r;uniform float t;uniform vec2 m;uniform float light;uniform float calm;
float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float n(vec2 p){vec2 i=floor(p),f=fract(p);vec2 u=f*f*(3.-2.*f);
  return mix(mix(h(i),h(i+vec2(1,0)),u.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),u.x),u.y);}
float fbm(vec2 p){float v=0.,a=.5;mat2 R=mat2(.8,.6,-.6,.8);for(int i=0;i<5;i++){v+=a*n(p);p=R*p*2.02;a*=.5;}return v;}
vec3 spectrum(float x){
  // one hue family: the studio rose, varied only in depth
  vec3 a=vec3(1.,.5,.74),b=vec3(.5,.2,.4);
  return mix(b,a,.5+.5*sin(6.2832*x));}
void main(){
  vec2 uv=gl_FragCoord.xy/r;vec2 p=(gl_FragCoord.xy-.5*r)/r.y;
  float s=t*(.035+.03*(1.-calm));
  vec2 mp=(m-.5)*vec2(r.x/r.y,-1.);
  p+=mp*.08;
  vec2 q=vec2(fbm(p*1.4+s),fbm(p*1.4-s+3.1));
  vec2 w=vec2(fbm(p*1.8+q*1.6+vec2(1.7,9.2)+s*1.4),fbm(p*1.8+q*1.6+vec2(8.3,2.8)-s));
  float f=fbm(p*1.2+w*1.8);
  float band=smoothstep(.25,.9,f)*(1.-smoothstep(.0,1.25,length(p-vec2(.35,.42)+mp*.25)));
  float veil=pow(smoothstep(.35,1.,fbm(p*3.+w*2.+s*2.)),2.2);
  vec3 col=spectrum(f*.9+w.x*.6+s*.5);
  float glow=exp(-3.2*length(p-mp*.9))*.35;
  float k=band*.85+veil*.35+glow;
  k*=mix(1.,.55,calm);
  vec3 dark=vec3(.027,.024,.047);
  vec3 night=dark+col*k*.36;
  vec3 day=mix(vec3(.965,.95,.985),col,k*.18);
  vec3 o=mix(night,day,light);
  float g=h(gl_FragCoord.xy+fract(t))*.035-.0175;
  o+=g*(1.-light*.5);
  float vig=smoothstep(1.4,.3,length(uv-.5)*1.6);
  o=mix(o*mix(.55,.92,light),o,vig);
  gl_FragColor=vec4(o,1.);
}`;

export default function Ambience({ calm }: { calm: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const palette = usePalette();
  const reduced = useMotionReduced();
  const state = useRef({ calm: calm ? 1 : 0, calmTarget: calm ? 1 : 0, light: palette === "pearl" ? 1 : 0, lightTarget: 0 });
  state.current.calmTarget = calm ? 1 : 0;
  state.current.lightTarget = palette === "pearl" ? 1 : 0;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, preserveDrawingBuffer: false, powerPreference: "low-power" });
    if (!gl) { canvas.dataset.failed = "true"; return; }
    const shader = (type: number, source: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, source);
      gl.compileShader(s);
      return s;
    };
    const program = gl.createProgram()!;
    gl.attachShader(program, shader(gl.VERTEX_SHADER, VERT));
    gl.attachShader(program, shader(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) { canvas.dataset.failed = "true"; return; }
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = {
      r: gl.getUniformLocation(program, "r"), t: gl.getUniformLocation(program, "t"), m: gl.getUniformLocation(program, "m"),
      light: gl.getUniformLocation(program, "light"), calm: gl.getUniformLocation(program, "calm"),
    };
    const s = state.current;
    s.light = s.lightTarget;
    s.calm = s.calmTarget;

    const scale = 0.42;
    const resize = () => {
      const w = Math.max(1, Math.round(window.innerWidth * scale));
      const h = Math.max(1, Math.round(window.innerHeight * scale));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; gl.viewport(0, 0, w, h); }
    };
    resize();
    window.addEventListener("resize", resize);

    const mouse = { x: 0.5, y: 0.4, tx: 0.5, ty: 0.4 };
    const pointer = (event: PointerEvent) => { mouse.tx = event.clientX / window.innerWidth; mouse.ty = event.clientY / window.innerHeight; };
    window.addEventListener("pointermove", pointer, { passive: true });

    let raf = 0;
    let lastDraw = 0;
    const start = performance.now() - Math.random() * 40000;
    const draw = (now: number) => {
      mouse.x += (mouse.tx - mouse.x) * 0.04;
      mouse.y += (mouse.ty - mouse.y) * 0.04;
      s.light += (s.lightTarget - s.light) * 0.08;
      s.calm += (s.calmTarget - s.calm) * 0.05;
      gl.uniform2f(u.r, canvas.width, canvas.height);
      gl.uniform1f(u.t, (now - start) / 1000);
      gl.uniform2f(u.m, mouse.x, mouse.y);
      gl.uniform1f(u.light, s.light);
      gl.uniform1f(u.calm, s.calm);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const budget = s.calmTarget ? 1000 / 14 : 1000 / 30;
      if (document.hidden || now - lastDraw < budget) return;
      lastDraw = now;
      draw(now);
    };
    if (reduced) {
      s.light = s.lightTarget;
      draw(performance.now());
      const redraw = () => { s.light = s.lightTarget; draw(performance.now()); };
      const timer = window.setInterval(redraw, 400);
      return () => { window.clearInterval(timer); window.removeEventListener("resize", resize); window.removeEventListener("pointermove", pointer); };
    }
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", pointer);
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    };
  }, [reduced]);

  return (
    <div className="ambience" aria-hidden="true">
      {/* A lost WebGL context cannot be reused: a new motion mode gets a fresh canvas. */}
      <canvas key={reduced ? "still" : "live"} ref={ref} />
      <div className="ambience-grain" />
    </div>
  );
}
