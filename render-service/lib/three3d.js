// Scene descriptor -> self-contained Three.js page.
//
// The scene JSON is DATA. This module owns all the rendering code; nothing the
// caller supplies is ever executed. That is what separates this from the
// custom.js escape hatch, and it is why this path is the default for 3D.
//
// Kinds: scatter (3D point cloud), bars (2.5D categorical), surface (z = grid),
// network (nodes + edges in 3D).

import { esc, TOKENS } from "./theme.js";

export function renderThree({ scene = {}, title = "3D view", theme = "dark", threeSrc = "" }) {
  if (!threeSrc) return { status: "scaffold", note: "three.js not bundled", title };

  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  const kind = String(scene.kind || "scatter").toLowerCase();

  const data = {
    kind,
    points: (Array.isArray(scene.points) ? scene.points : []).slice(0, 8000).map((p) => ({
      x: +p.x || 0,
      y: +p.y || 0,
      z: +p.z || 0,
      value: p.value === undefined ? null : +p.value || 0,
      label: p.label ? String(p.label).slice(0, 60) : "",
      group: p.group ? String(p.group).slice(0, 40) : "",
    })),
    edges: (Array.isArray(scene.edges) ? scene.edges : []).slice(0, 4000).map((e) => ({
      from: +e.from || 0,
      to: +e.to || 0,
      weight: +e.weight || 1,
    })),
    grid: Array.isArray(scene.grid) ? scene.grid.slice(0, 200).map((r) => r.slice(0, 200).map(Number)) : null,
    axes: {
      x: String(scene.axes?.x ?? "x"),
      y: String(scene.axes?.y ?? "y"),
      z: String(scene.axes?.z ?? "z"),
    },
    colors: { accent: t.accent, fg: t.fg, muted: t.fgMuted, bg: t.bg, grid: t.grid },
    autorotate: scene.autorotate !== false,
  };

  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:${t.bg};color:${t.fg};
  font-family:ui-sans-serif,system-ui,sans-serif}
#c{display:block;width:100%;height:100%}
.hud{position:fixed;top:12px;left:14px;pointer-events:none}
.hud .eyebrow{font-family:ui-monospace,monospace;font-size:10px;letter-spacing:.14em;
  text-transform:uppercase;color:${t.fgFaint}}
.hud h1{font-family:Georgia,serif;font-size:18px;font-weight:600;margin:2px 0 0;letter-spacing:-.02em}
.hint{position:fixed;bottom:12px;left:14px;font-size:11px;color:${t.fgFaint}}
.tip{position:fixed;padding:4px 8px;background:${t.surface};border:1px solid ${t.border};
  font-size:11.5px;color:${t.fg};pointer-events:none;display:none;transform:translate(10px,-50%)}
.ctrls{position:fixed;top:12px;right:14px;display:flex;gap:6px}
.ctrls button{background:${t.surface};border:1px solid ${t.border};color:${t.fgMuted};
  font-size:11px;padding:4px 9px;cursor:pointer}
.ctrls button:hover{border-color:${t.accent};color:${t.accent}}
</style></head><body>
<canvas id="c"></canvas>
<div class="hud"><div class="eyebrow">Weave</div><h1>${esc(title)}</h1></div>
<div class="ctrls"><button id="spin">Pause spin</button><button id="reset">Reset view</button></div>
<div class="hint">drag to orbit · scroll to zoom</div>
<div class="tip" id="tip"></div>
<script>${threeSrc}</script>
<script>
const D = ${JSON.stringify(data)};
const C = D.colors;
const cv = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({canvas:cv, antialias:true});
renderer.setPixelRatio(Math.min(2, devicePixelRatio||1));
const scene = new THREE.Scene();
scene.background = new THREE.Color(C.bg);
const cam = new THREE.PerspectiveCamera(55, 1, 0.1, 2000);
scene.add(new THREE.AmbientLight(0xffffff, 0.75));
const dl = new THREE.DirectionalLight(0xffffff, 0.9); dl.position.set(6,12,8); scene.add(dl);

// ---- normalise into a unit-ish box so any data range frames correctly ----
function extent(getter, fallback){
  const vals = D.points.map(getter).filter(v=>isFinite(v));
  if(!vals.length) return fallback;
  return [Math.min(...vals), Math.max(...vals)];
}
const ex = extent(p=>p.x,[0,1]), ey = extent(p=>p.y,[0,1]), ez = extent(p=>p.z,[0,1]);
const S = 10;
const norm = (v,[lo,hi]) => hi===lo ? 0 : ((v-lo)/(hi-lo) - 0.5) * S;

const grid = new THREE.GridHelper(S*1.3, 13, C.grid, C.grid);
grid.material.opacity = 0.35; grid.material.transparent = true;
grid.position.y = -S/2 - 0.4;
scene.add(grid);
scene.add(new THREE.AxesHelper(S*0.62));

const meshes = [];
const accent = new THREE.Color(C.accent);

function colourFor(v){
  if(v===null) return accent;
  // Single-hue ramp: light -> saturated accent. A rainbow would invent
  // categorical meaning in what is a continuous quantity.
  const c = accent.clone();
  const hsl = {}; c.getHSL(hsl);
  return c.setHSL(hsl.h, 0.35 + 0.55*v, 0.72 - 0.34*v);
}

if(D.kind === 'surface' && D.grid){
  const rows = D.grid.length, cols = D.grid[0] ? D.grid[0].length : 0;
  let zmin=Infinity, zmax=-Infinity;
  for(const r of D.grid) for(const v of r){ if(isFinite(v)){ if(v<zmin)zmin=v; if(v>zmax)zmax=v; } }
  const geo = new THREE.PlaneGeometry(S, S, cols-1, rows-1);
  const pos = geo.attributes.position;
  const colors = [];
  for(let i=0;i<pos.count;i++){
    const r = Math.floor(i/cols), cc = i%cols;
    const v = (D.grid[r] && isFinite(D.grid[r][cc])) ? D.grid[r][cc] : 0;
    const nv = zmax===zmin ? 0.5 : (v-zmin)/(zmax-zmin);
    pos.setZ(i, nv*S*0.6);
    const col = colourFor(nv);
    colors.push(col.r, col.g, col.b);
  }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(colors,3));
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
    vertexColors:true, side:THREE.DoubleSide, flatShading:false, roughness:.85}));
  mesh.rotation.x = -Math.PI/2;
  scene.add(mesh);
} else if(D.kind === 'bars'){
  const vals = D.points.map(p=>p.value===null?0:p.value);
  const vmax = Math.max(1, ...vals.map(Math.abs));
  D.points.forEach((p,i)=>{
    const hgt = Math.abs((p.value===null?0:p.value)/vmax) * S * 0.8 || 0.05;
    const g = new THREE.BoxGeometry(S*0.055, hgt, S*0.055);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({
      color: colourFor(Math.abs((p.value===null?0:p.value))/vmax), roughness:.7}));
    m.position.set(norm(p.x,ex), -S/2 + hgt/2, norm(p.z,ez));
    m.userData = p; scene.add(m); meshes.push(m);
  });
} else if(D.kind === 'network'){
  const geo = new THREE.SphereGeometry(0.18, 18, 18);
  D.points.forEach((p)=>{
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
      color: colourFor(p.value===null?0.6:p.value), roughness:.6}));
    m.position.set(norm(p.x,ex), norm(p.y,ey), norm(p.z,ez));
    m.userData = p; scene.add(m); meshes.push(m);
  });
  const lg = new THREE.BufferGeometry();
  const verts = [];
  D.edges.forEach(e=>{
    const a = D.points[e.from], b = D.points[e.to];
    if(!a||!b) return;
    verts.push(norm(a.x,ex),norm(a.y,ey),norm(a.z,ez), norm(b.x,ex),norm(b.y,ey),norm(b.z,ez));
  });
  if(verts.length){
    lg.setAttribute('position', new THREE.Float32BufferAttribute(verts,3));
    scene.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
      color:new THREE.Color(C.muted), transparent:true, opacity:.32})));
  }
} else {
  const vals = D.points.map(p=>p.value).filter(v=>v!==null);
  const vmin = vals.length?Math.min(...vals):0, vmax = vals.length?Math.max(...vals):1;
  const geo = new THREE.SphereGeometry(0.15, 16, 16);
  D.points.forEach((p)=>{
    const nv = p.value===null ? 0.6 : (vmax===vmin?0.6:(p.value-vmin)/(vmax-vmin));
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({color:colourFor(nv), roughness:.6}));
    m.position.set(norm(p.x,ex), norm(p.y,ey), norm(p.z,ez));
    m.scale.setScalar(0.7 + 1.5*nv);
    m.userData = p; scene.add(m); meshes.push(m);
  });
}

// ---- orbit ----
let az = 0.6, el = 0.5, dist = S*2.1, spin = D.autorotate;
let down=false, px=0, py=0;
function place(){
  cam.position.set(
    Math.cos(el)*Math.sin(az)*dist,
    Math.sin(el)*dist,
    Math.cos(el)*Math.cos(az)*dist);
  cam.lookAt(0,0,0);
}
cv.addEventListener('pointerdown', e=>{down=true;px=e.clientX;py=e.clientY;cv.setPointerCapture(e.pointerId)});
addEventListener('pointerup', ()=>down=false);
addEventListener('pointermove', e=>{
  if(!down) return;
  az -= (e.clientX-px)*0.007;
  el = Math.max(-1.45, Math.min(1.45, el + (e.clientY-py)*0.007));
  px=e.clientX; py=e.clientY;
});
cv.addEventListener('wheel', e=>{
  e.preventDefault();
  dist = Math.max(S*0.6, Math.min(S*6, dist * (1 + Math.sign(e.deltaY)*0.08)));
}, {passive:false});
document.getElementById('spin').addEventListener('click', function(){
  spin=!spin; this.textContent = spin ? 'Pause spin' : 'Resume spin';
});
document.getElementById('reset').addEventListener('click', ()=>{ az=0.6; el=0.5; dist=S*2.1; });

// ---- hover labels ----
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
const tip = document.getElementById('tip');
addEventListener('pointermove', e=>{
  if(!meshes.length || down) { tip.style.display='none'; return; }
  ndc.x = (e.clientX/innerWidth)*2-1; ndc.y = -(e.clientY/innerHeight)*2+1;
  ray.setFromCamera(ndc, cam);
  const hit = ray.intersectObjects(meshes, false)[0];
  if(hit && hit.object.userData && hit.object.userData.label){
    const d = hit.object.userData;
    tip.style.display='block'; tip.style.left=e.clientX+'px'; tip.style.top=e.clientY+'px';
    tip.textContent = d.label + (d.value!==null ? ' · '+d.value : '');
  } else tip.style.display='none';
});

function resize(){
  const w=innerWidth,h=innerHeight;
  renderer.setSize(w,h,false); cam.aspect=w/h; cam.updateProjectionMatrix();
}
addEventListener('resize', resize); resize();
(function loop(){
  requestAnimationFrame(loop);
  if(spin && !down) az += 0.0022;
  place(); renderer.render(scene,cam);
})();
window.__WEAVE_READY = true;
</script></body></html>`;

  return {
    status: "ok",
    title,
    kind,
    html,
    point_count: data.points.length,
    edge_count: data.edges.length,
  };
}
