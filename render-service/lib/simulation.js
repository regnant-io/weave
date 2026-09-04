// Spec -> interactive, parameterised concept simulation.
//
// This is the piece that makes Weave a *learning* tool rather than an answering
// tool. A static chart tells a student what the answer is; a simulation with a
// slider lets them discover why. "Drag theta and watch the range peak at 45°"
// builds an intuition that no paragraph does.
//
// A spec declares: parameters (sliders), an independent variable, and a set of
// curves or bodies defined as expressions over those parameters. All maths goes
// through the sandboxed evaluator in expr.js — no eval, ever.
//
// Modes:
//   plot     — y = f(x) curves, redrawn live as sliders move
//   motion   — 2D parametric bodies animated over time, with an optional trail
//   field    — vector field over a grid (gradients, flows, forces)
//   bar      — categorical values recomputed from parameters

import { EXPR_RUNTIME, validateExpressions } from "./expr.js";
import { esc, page, palette, TOKENS } from "./theme.js";

function collectExpressions(spec) {
  const out = [];
  for (const c of spec.curves || []) out.push(c.y, c.x);
  for (const b of spec.bodies || []) out.push(b.x, b.y, b.r, b.color_by);
  for (const f of spec.field ? [spec.field] : []) out.push(f.u, f.v);
  for (const b of spec.bars || []) out.push(b.value);
  return out.filter((s) => typeof s === "string" && s.trim());
}

export function renderSimulation({ spec = {}, title = "Simulation", theme = "light" }) {
  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  const cols = palette(theme);
  const mode = String(spec.mode || "plot").toLowerCase();

  // Validate before persisting: a spec with a broken formula should fail loudly
  // at generation time, where the model can be told to fix it, rather than
  // silently rendering an empty chart the user has to debug.
  const bad = validateExpressions(collectExpressions(spec));
  if (bad) return { status: "error", error: `invalid expression ${bad}` };

  const params = (spec.params || []).slice(0, 10).map((p) => ({
    name: String(p.name || "p").replace(/[^A-Za-z0-9_]/g, ""),
    label: String(p.label ?? p.name ?? "p"),
    min: Number(p.min ?? 0),
    max: Number(p.max ?? 10),
    // A step of 0 (or an absent range) would freeze the slider, so fall back.
    step: Number(p.step) || (Number(p.max ?? 10) - Number(p.min ?? 0)) / 100 || 0.01,
    value: Number(p.value ?? p.default ?? p.min ?? 0),
    unit: p.unit ? String(p.unit) : "",
  }));

  const cfg = {
    mode,
    params,
    x: {
      name: String(spec.x?.name || "x"),
      min: Number(spec.x?.min ?? 0),
      max: Number(spec.x?.max ?? 10),
      label: String(spec.x?.label ?? spec.x?.name ?? "x"),
      samples: Math.min(2000, Math.max(40, Number(spec.x?.samples ?? 400))),
    },
    y: {
      label: String(spec.y?.label ?? "y"),
      min: spec.y?.min === undefined ? null : Number(spec.y.min),
      max: spec.y?.max === undefined ? null : Number(spec.y.max),
    },
    curves: (spec.curves || []).slice(0, 8).map((c, i) => ({
      label: String(c.label ?? `series ${i + 1}`),
      y: String(c.y ?? "0"),
      color: c.color || cols[i % cols.length],
      dash: c.dash ? "6 4" : "",
    })),
    bodies: (spec.bodies || []).slice(0, 40).map((b, i) => ({
      label: String(b.label ?? ""),
      x: String(b.x ?? "0"),
      y: String(b.y ?? "0"),
      r: String(b.r ?? "0.25"),
      color: b.color || cols[i % cols.length],
      trail: b.trail !== false,
    })),
    field: spec.field
      ? {
          u: String(spec.field.u ?? "0"),
          v: String(spec.field.v ?? "0"),
          density: Math.min(30, Math.max(4, Number(spec.field.density ?? 16))),
        }
      : null,
    bars: (spec.bars || []).slice(0, 24).map((b, i) => ({
      label: String(b.label ?? `#${i + 1}`),
      value: String(b.value ?? "0"),
      color: b.color || cols[i % cols.length],
    })),
    time: {
      enabled: mode === "motion" || Boolean(spec.animate),
      max: Number(spec.time?.max ?? 10),
      speed: Number(spec.time?.speed ?? 1),
      loop: spec.time?.loop !== false,
    },
    view: {
      xmin: Number(spec.view?.xmin ?? spec.x?.min ?? -1),
      xmax: Number(spec.view?.xmax ?? spec.x?.max ?? 10),
      ymin: Number(spec.view?.ymin ?? -1),
      ymax: Number(spec.view?.ymax ?? 10),
      // Whether the y-window was CHOSEN or defaulted. A default window is
      // almost always wrong for a parameterised simulation: the whole point is
      // that dragging a slider changes the shape of the answer, and a fixed
      // window means half the slider range draws a curve that leaves the top of
      // the chart. Recorded here so the page can fit the window to the data.
      autoY: spec.view?.ymin === undefined && spec.view?.ymax === undefined,
    },
    readouts: (spec.readouts || []).slice(0, 6).map((r) => ({
      label: String(r.label ?? ""),
      expr: String(r.expr ?? "0"),
      unit: r.unit ? String(r.unit) : "",
    })),
    colors: {
      fg: t.fg,
      muted: t.fgMuted,
      faint: t.fgFaint,
      grid: t.grid,
      accent: t.accent,
      bg: t.bg,
      surface: t.surface2,
    },
  };

  const controls = params
    .map(
      (p) => `<label class="ctl">
  <span class="ctl-h"><span>${esc(p.label)}</span><output id="out_${p.name}">${p.value}${esc(p.unit)}</output></span>
  <input type="range" id="p_${p.name}" data-p="${p.name}"
    min="${p.min}" max="${p.max}" step="${p.step}" value="${p.value}">
</label>`,
    )
    .join("\n");

  const readouts = cfg.readouts
    .map((r) => `<div class="ro"><span class="eyebrow">${esc(r.label)}</span><b id="ro_${cfg.readouts.indexOf(r)}">—</b></div>`)
    .join("");

  const css = `
.sim{display:grid;grid-template-columns:1fr 250px;gap:18px;align-items:start}
@media(max-width:760px){.sim{grid-template-columns:1fr}}
canvas{width:100%;height:auto;display:block;border:1px solid var(--border);background:var(--bg)}
.panel{border:1px solid var(--border);padding:12px;background:var(--bg-subtle)}
.ctl{display:block;margin-bottom:14px}
.ctl-h{display:flex;justify-content:space-between;font-size:12px;color:var(--fg-muted);margin-bottom:5px}
.ctl-h output{font-family:ui-monospace,monospace;color:var(--accent)}
input[type=range]{width:100%;accent-color:var(--accent);height:18px}
.ro{display:flex;justify-content:space-between;align-items:baseline;padding:5px 0;border-top:1px solid var(--border)}
.ro b{font-family:ui-monospace,monospace;font-size:13px;color:var(--fg)}
.tbar{display:flex;align-items:center;gap:8px;margin-top:10px}
.tbar input[type=range]{flex:1}
.legend i{width:14px;height:2px}`;

  const script = `${EXPR_RUNTIME}
(function(){
var CFG = ${JSON.stringify(cfg)};
var E = globalThis.WeaveExpr;
var cv = document.getElementById('cv'), ctx = cv.getContext('2d');
var scope = {}; CFG.params.forEach(function(p){ scope[p.name] = p.value; });
scope.t = 0;

// Compile once. Recompiling per frame would dominate the frame budget.
var curves = CFG.curves.map(function(c){ return {c:c, f:E.safe(c.y)}; });
var bodies = CFG.bodies.map(function(b){ return {b:b, fx:E.safe(b.x), fy:E.safe(b.y), fr:E.safe(b.r), trail:[]}; });
var bars   = CFG.bars.map(function(b){ return {b:b, f:E.safe(b.value)}; });
var field  = CFG.field ? {u:E.safe(CFG.field.u), v:E.safe(CFG.field.v), d:CFG.field.density} : null;
var ros    = CFG.readouts.map(function(r){ return {r:r, f:E.safe(r.expr)}; });

var W=0,H=0,DPR=1;
function resize(){
  DPR = Math.min(2, window.devicePixelRatio||1);
  var rect = cv.getBoundingClientRect();
  W = Math.max(320, rect.width|0);
  // Fill the room the artifact frame actually gives us. A fixed 0.58 aspect
  // ratio left a third of the panel empty below the chart on every desktop
  // viewport, which reads as an unfinished layout rather than a deliberate one.
  var avail = (window.innerHeight || 640) - rect.top - 28;
  H = Math.max(260, Math.min(Math.round(W*0.95), Math.round(avail)));
  cv.width = W*DPR; cv.height = H*DPR; cv.style.height = H+'px';
  ctx.setTransform(DPR,0,0,DPR,0,0);
  draw();
}

var V = CFG.view;
function sx(x){ return 46 + (x - V.xmin)/(V.xmax - V.xmin) * (W - 62); }
function sy(y){ return (H - 34) - (y - V.ymin)/(V.ymax - V.ymin) * (H - 50); }

function axes(){
  var C = CFG.colors;
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle = C.grid; ctx.lineWidth = 1; ctx.font='10px ui-monospace,monospace';
  ctx.fillStyle = C.faint;
  var stepsX = 6, stepsY = 5;
  for(var i=0;i<=stepsX;i++){
    var xv = V.xmin + (V.xmax-V.xmin)*i/stepsX, px = sx(xv);
    ctx.globalAlpha=.5; ctx.beginPath(); ctx.moveTo(px,10); ctx.lineTo(px,H-34); ctx.stroke(); ctx.globalAlpha=1;
    ctx.textAlign='center'; ctx.fillText(fmt(xv), px, H-18);
  }
  for(var j=0;j<=stepsY;j++){
    var yv = V.ymin + (V.ymax-V.ymin)*j/stepsY, py = sy(yv);
    ctx.globalAlpha=.5; ctx.beginPath(); ctx.moveTo(46,py); ctx.lineTo(W-16,py); ctx.stroke(); ctx.globalAlpha=1;
    ctx.textAlign='right'; ctx.fillText(fmt(yv), 41, py+3);
  }
  // Emphasise the zero axes — they carry meaning the gridlines don't.
  ctx.strokeStyle = C.muted; ctx.globalAlpha=.55; ctx.lineWidth=1;
  if(V.ymin<0&&V.ymax>0){ctx.beginPath();ctx.moveTo(46,sy(0));ctx.lineTo(W-16,sy(0));ctx.stroke();}
  if(V.xmin<0&&V.xmax>0){ctx.beginPath();ctx.moveTo(sx(0),10);ctx.lineTo(sx(0),H-34);ctx.stroke();}
  ctx.globalAlpha=1;
}
function fmt(v){
  if(!isFinite(v)) return '';
  var a=Math.abs(v);
  if(a>=1000||(a<0.01&&a>0)) return v.toExponential(1);
  return (Math.round(v*100)/100).toString();
}

function drawCurves(){
  var n = CFG.x.samples;
  curves.forEach(function(cc){
    ctx.beginPath(); ctx.strokeStyle = cc.c.color; ctx.lineWidth = 2;
    if(cc.c.dash) ctx.setLineDash([6,4]); else ctx.setLineDash([]);
    var started=false;
    for(var i=0;i<=n;i++){
      var xv = V.xmin + (V.xmax-V.xmin)*i/n;
      scope[CFG.x.name] = xv;
      var yv = cc.f(scope);
      if(!isFinite(yv)){ started=false; continue; }      // NaN = genuine gap
      var px=sx(xv), py=sy(yv);
      if(py<-1e4||py>1e4){ started=false; continue; }
      if(started) ctx.lineTo(px,py); else { ctx.moveTo(px,py); started=true; }
    }
    ctx.stroke(); ctx.setLineDash([]);
  });
}

function drawBodies(){
  bodies.forEach(function(bb){
    var x=bb.fx(scope), y=bb.fy(scope), r=Math.abs(bb.fr(scope))||0.2;
    if(!isFinite(x)||!isFinite(y)) return;
    if(bb.b.trail){
      bb.trail.push([x,y]); if(bb.trail.length>420) bb.trail.shift();
      ctx.beginPath(); ctx.strokeStyle=bb.b.color; ctx.globalAlpha=.28; ctx.lineWidth=1.5;
      bb.trail.forEach(function(p,i){ i?ctx.lineTo(sx(p[0]),sy(p[1])):ctx.moveTo(sx(p[0]),sy(p[1])); });
      ctx.stroke(); ctx.globalAlpha=1;
    }
    var pr = Math.max(3, Math.abs(sx(r)-sx(0)));
    ctx.beginPath(); ctx.fillStyle=bb.b.color;
    ctx.arc(sx(x), sy(y), Math.min(40,pr), 0, Math.PI*2); ctx.fill();
    if(bb.b.label){
      ctx.fillStyle=CFG.colors.muted; ctx.font='11px ui-sans-serif,system-ui';
      ctx.textAlign='center'; ctx.fillText(bb.b.label, sx(x), sy(y)-Math.min(40,pr)-6);
    }
  });
}

function drawField(){
  if(!field) return;
  var d=field.d, C=CFG.colors;
  var stepX=(V.xmax-V.xmin)/d, stepY=(V.ymax-V.ymin)/d;
  var maxLen=0, vecs=[];
  for(var i=0;i<=d;i++) for(var j=0;j<=d;j++){
    var xv=V.xmin+stepX*i, yv=V.ymin+stepY*j;
    scope[CFG.x.name]=xv; scope.x=xv; scope.y=yv;
    var u=field.u(scope), v=field.v(scope);
    if(!isFinite(u)||!isFinite(v)) continue;
    var L=Math.hypot(u,v); if(L>maxLen) maxLen=L;
    vecs.push([xv,yv,u,v,L]);
  }
  var cell=Math.min((W-62)/(d+1),(H-50)/(d+1))*0.82;
  vecs.forEach(function(q){
    var s = maxLen ? (q[4]/maxLen) : 0;
    var nx = q[4] ? q[2]/q[4] : 0, ny = q[4] ? q[3]/q[4] : 0;
    var x0=sx(q[0]), y0=sy(q[1]);
    var x1=x0+nx*cell*s, y1=y0-ny*cell*s;
    ctx.strokeStyle=C.accent; ctx.globalAlpha=0.25+0.75*s; ctx.lineWidth=1.2;
    ctx.beginPath(); ctx.moveTo(x0,y0); ctx.lineTo(x1,y1); ctx.stroke();
    ctx.beginPath(); ctx.arc(x1,y1,1.8,0,Math.PI*2); ctx.fillStyle=C.accent; ctx.fill();
  });
  ctx.globalAlpha=1;
}

function drawBars(){
  if(!bars.length) return;
  var C=CFG.colors, n=bars.length;
  var vals=bars.map(function(bb){ var v=bb.f(scope); return isFinite(v)?v:0; });
  var lo=Math.min(0,Math.min.apply(null,vals)), hi=Math.max.apply(null,vals)||1;
  var padL=46, padB=40, plotW=W-padL-20, plotH=H-padB-16;
  var bw=plotW/n*0.66, gap=plotW/n;
  ctx.clearRect(0,0,W,H);
  ctx.strokeStyle=C.grid; ctx.fillStyle=C.faint; ctx.font='10px ui-monospace,monospace';
  for(var g=0;g<=4;g++){
    var gv=lo+(hi-lo)*g/4, gy=16+plotH-(gv-lo)/(hi-lo||1)*plotH;
    ctx.globalAlpha=.5;ctx.beginPath();ctx.moveTo(padL,gy);ctx.lineTo(W-20,gy);ctx.stroke();ctx.globalAlpha=1;
    ctx.textAlign='right';ctx.fillText(fmt(gv),padL-5,gy+3);
  }
  vals.forEach(function(v,i){
    var bh=(v-lo)/(hi-lo||1)*plotH;
    var x=padL+i*gap+(gap-bw)/2, y=16+plotH-bh;
    ctx.fillStyle=bars[i].b.color; ctx.fillRect(x,y,bw,bh);
    ctx.fillStyle=C.muted; ctx.font='11px ui-sans-serif,system-ui'; ctx.textAlign='center';
    ctx.fillText(bars[i].b.label, x+bw/2, H-18);
  });
}

function updateReadouts(){
  ros.forEach(function(rr,i){
    var el=document.getElementById('ro_'+i); if(!el) return;
    var v=rr.f(scope);
    el.textContent = isFinite(v) ? (fmt(v)+(rr.r.unit?' '+rr.r.unit:'')) : '—';
  });
}

/**
 * Fit the y-window to what is actually being drawn.
 *
 * Only when the spec did not choose one. A projectile launched at 45 degrees
 * and 50 m/s peaks around 64m; the default window stops at 10, so the curve
 * left the top of the chart and the simulation looked broken while being
 * arithmetically perfect. Refitting on every parameter change is what makes the
 * sliders worth dragging.
 */
function fitY(){
  if(!V.autoY) return;
  var lo=Infinity, hi=-Infinity, n=CFG.x.samples;
  var saved = scope[CFG.x.name];
  curves.forEach(function(cc){
    for(var i=0;i<=n;i++){
      var xv = V.xmin + (V.xmax-V.xmin)*i/n;
      scope[CFG.x.name] = xv;
      var yv = cc.f(scope);
      if(isFinite(yv)){ if(yv<lo) lo=yv; if(yv>hi) hi=yv; }
    }
  });
  scope[CFG.x.name] = saved;
  bodies.forEach(function(bb){
    var yv = bb.fy(scope);
    if(isFinite(yv)){ if(yv<lo) lo=yv; if(yv>hi) hi=yv; }
  });
  if(!isFinite(lo) || !isFinite(hi)) return;
  if(hi - lo < 1e-9){ hi = lo + 1; }
  var pad = (hi - lo) * 0.12;
  V.ymin = lo - pad;
  V.ymax = hi + pad;
  // Don't invent ground below zero for a quantity that never goes negative:
  // a height axis starting at -8m reads as an error.
  if(lo >= 0) V.ymin = 0;
}

function draw(){
  if(CFG.mode==='bar'){ drawBars(); }
  else { fitY(); axes(); drawField(); drawCurves(); drawBodies(); }
  updateReadouts();
}

// ---- controls ----
CFG.params.forEach(function(p){
  var el=document.getElementById('p_'+p.name), out=document.getElementById('out_'+p.name);
  if(!el) return;
  el.addEventListener('input', function(){
    scope[p.name]=parseFloat(el.value);
    if(out) out.textContent=el.value+(p.unit||'');
    bodies.forEach(function(b){ b.trail.length=0; });   // stale trail = wrong story
    if(!running) draw();
  });
});

// ---- time ----
var running=false, last=0, tEl=document.getElementById('tslider'), playBtn=document.getElementById('play');
function setT(v){
  scope.t=v;
  if(tEl) tEl.value=String(v);
  var lbl=document.getElementById('tlabel'); if(lbl) lbl.textContent='t = '+fmt(v);
}
if(tEl){
  tEl.addEventListener('input',function(){
    running=false; if(playBtn) playBtn.textContent='Play';
    bodies.forEach(function(b){ b.trail.length=0; });
    setT(parseFloat(tEl.value)); draw();
  });
}
if(playBtn){
  playBtn.addEventListener('click',function(){
    running=!running; playBtn.textContent=running?'Pause':'Play';
    last=performance.now(); if(running) requestAnimationFrame(loop);
  });
}
var resetBtn=document.getElementById('reset');
if(resetBtn) resetBtn.addEventListener('click',function(){
  running=false; if(playBtn) playBtn.textContent='Play';
  bodies.forEach(function(b){ b.trail.length=0; }); setT(0); draw();
});
function loop(now){
  if(!running) return;
  var dt=Math.min(0.05,(now-last)/1000); last=now;
  var nt=scope.t+dt*CFG.time.speed;
  if(nt>CFG.time.max){
    if(CFG.time.loop){ nt=0; bodies.forEach(function(b){ b.trail.length=0; }); }
    else { nt=CFG.time.max; running=false; if(playBtn) playBtn.textContent='Play'; }
  }
  setT(nt); draw();
  if(running) requestAnimationFrame(loop);
}

addEventListener('resize', resize);
setT(0); resize();
})();`;

  const timeBar = cfg.time.enabled
    ? `<div class="tbar">
  <button class="btn primary" id="play">Play</button>
  <button class="btn" id="reset">Reset</button>
  <input type="range" id="tslider" min="0" max="${cfg.time.max}" step="${cfg.time.max / 500}" value="0">
  <span class="eyebrow" id="tlabel">t = 0</span>
</div>`
    : "";

  const legend = cfg.curves.length
    ? `<div class="legend">${cfg.curves
        .map((c) => `<span><i style="background:${c.color}"></i>${esc(c.label)}</span>`)
        .join("")}</div>`
    : "";

  const body = `<div class="sim">
  <div>
    <canvas id="cv" role="img" aria-label="${esc(title)}"></canvas>
    ${timeBar}
    ${legend}
  </div>
  <div class="panel">
    <div class="eyebrow" style="margin-bottom:10px">Parameters</div>
    ${controls || '<p class="caption" style="margin:0">No adjustable parameters.</p>'}
    ${readouts ? `<div style="margin-top:14px">${readouts}</div>` : ""}
  </div>
</div>`;

  return {
    status: "ok",
    mode,
    html: page({ title, subtitle: spec.description, theme, caption: spec.caption, css, body, script }),
  };
}
