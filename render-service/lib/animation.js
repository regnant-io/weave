// Spec -> self-drawing animated SVG explainer.
//
// The whiteboard idiom: a diagram that draws itself one stroke at a time while
// a caption explains that stroke. It scales the same trick as the Weave
// wordmark — stroke-dashoffset sequencing — from a logo to a teaching device.
//
// Why this and not a video: it is a few KB, it is vector-crisp at any zoom, it
// needs no codec, it is scrubbable, and it degrades to a complete static
// diagram when animation is off. On a low-end Android over patchy mobile data
// — the actual target device — that matters more than production value.

import { esc, page, palette, TOKENS } from "./theme.js";

/** Turn a step's geometry into a single stroked path. */
function pathFor(step) {
  if (step.path) return String(step.path);
  const p = step.points || [];
  if (step.kind === "line" && p.length >= 2) {
    return `M ${p.map((q) => `${q[0]} ${q[1]}`).join(" L ")}`;
  }
  if (step.kind === "rect") {
    const [x, y, w, h] = step.rect || [0, 0, 10, 10];
    return `M ${x} ${y} H ${x + w} V ${y + h} H ${x} Z`;
  }
  if (step.kind === "circle") {
    const [cx, cy, r] = step.circle || [0, 0, 10];
    return `M ${cx - r} ${cy} a ${r} ${r} 0 1 0 ${r * 2} 0 a ${r} ${r} 0 1 0 ${-r * 2} 0`;
  }
  if (step.kind === "arrow" && p.length >= 2) {
    return `M ${p.map((q) => `${q[0]} ${q[1]}`).join(" L ")}`;
  }
  if (p.length >= 2) return `M ${p.map((q) => `${q[0]} ${q[1]}`).join(" L ")}`;
  return "";
}

export function renderAnimation({ spec = {}, title = "Explainer", theme = "light" }) {
  const t = TOKENS[theme === "dark" ? "dark" : "light"];
  const cols = palette(theme);
  const steps = (spec.steps || []).slice(0, 40);
  if (!steps.length) return { status: "error", error: "animation spec has no steps" };

  const vw = Number(spec.width ?? 720);
  const vh = Number(spec.height ?? 420);
  const perStep = Number(spec.step_duration ?? 1100);

  const layers = [];
  const captions = [];
  let delay = 0;

  steps.forEach((s, i) => {
    const colour = s.accent ? t.accent : s.color || cols[i % cols.length];
    const dur = Number(s.duration ?? perStep);
    const d = pathFor(s);

    if (d) {
      layers.push(
        `<path class="stroke" data-i="${i}" d="${esc(d)}" fill="${s.fill ? colour + "22" : "none"}"
  stroke="${colour}" stroke-width="${Number(s.width ?? 2.4)}" stroke-linecap="round" stroke-linejoin="round"
  pathLength="1" style="--d:${dur}ms;--delay:${delay}ms"
  ${s.kind === "arrow" ? 'marker-end="url(#arwA)"' : ""}/>`,
      );
    }
    if (s.text) {
      const [tx, ty] = s.text_at || [vw / 2, vh - 18];
      layers.push(
        `<text class="lbl" data-i="${i}" x="${tx}" y="${ty}"
  text-anchor="${s.text_anchor || "middle"}" font-size="${Number(s.text_size ?? 14)}"
  font-family="ui-sans-serif,system-ui,sans-serif" fill="${t.fg}"
  style="--delay:${delay + Math.round(dur * 0.55)}ms">${esc(s.text)}</text>`,
      );
    }
    captions.push({ i, text: s.caption || s.text || "", at: delay, dur });
    delay += dur + Number(s.pause ?? 180);
  });

  const total = delay;

  const css = `
.stage{border:1px solid var(--border);background:var(--bg);position:relative}
svg.scene{display:block;width:100%;height:auto}
.stroke{stroke-dasharray:1 1;stroke-dashoffset:1;
  animation:drawIt var(--d) cubic-bezier(.65,0,.35,1) var(--delay) forwards}
@keyframes drawIt{to{stroke-dashoffset:0}}
.lbl{opacity:0;animation:appear 420ms ease-out var(--delay) forwards}
@keyframes appear{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.narration{margin-top:12px;min-height:44px;border-left:2px solid var(--accent);padding-left:12px}
.narration p{margin:0;font-family:Georgia,serif;font-size:14.5px;line-height:1.6;color:var(--fg-muted);
  opacity:0;transition:opacity .3s}
.narration p.on{opacity:1}
.abar{display:flex;align-items:center;gap:8px;margin-top:12px}
.abar input{flex:1;accent-color:var(--accent)}
.replaying .stroke,.replaying .lbl{animation:none!important}
@media (prefers-reduced-motion:reduce){
  .stroke{stroke-dashoffset:0;animation:none}
  .lbl{opacity:1;animation:none}
  .narration p{opacity:1}
}`;

  const script = `
(function(){
  var TOTAL=${total};
  var CAPS=${JSON.stringify(captions.map((c) => ({ at: c.at, dur: c.dur, i: c.i })))};
  var scene=document.getElementById('scene');
  var caps=[].slice.call(document.querySelectorAll('.narration p'));
  var bar=document.getElementById('abar'), btn=document.getElementById('areplay');
  var t0=performance.now(), raf=null;

  function showCap(idx){
    caps.forEach(function(p,k){ p.classList.toggle('on', k===idx); });
  }
  function currentIdx(ms){
    var idx=0;
    for(var i=0;i<CAPS.length;i++) if(ms>=CAPS[i].at) idx=i;
    return idx;
  }
  function tick(now){
    var ms=Math.min(TOTAL, now-t0);
    if(bar) bar.value=String(ms);
    showCap(currentIdx(ms));
    if(ms<TOTAL) raf=requestAnimationFrame(tick); else raf=null;
  }
  function replay(){
    if(raf) cancelAnimationFrame(raf);
    // Force the CSS animations to restart by detaching and reflowing.
    scene.classList.add('replaying');
    void scene.offsetWidth;
    scene.classList.remove('replaying');
    t0=performance.now();
    raf=requestAnimationFrame(tick);
  }
  if(btn) btn.addEventListener('click', replay);
  if(bar) bar.addEventListener('input', function(){
    // Scrubbing shows the narration for that moment; the drawing itself is CSS
    // driven, so we pause it at the scrubbed position rather than re-timing it.
    if(raf){ cancelAnimationFrame(raf); raf=null; }
    showCap(currentIdx(parseFloat(bar.value)));
  });
  showCap(0);
  raf=requestAnimationFrame(tick);
})();`;

  const body = `<div class="stage">
<svg id="scene" class="scene" viewBox="0 0 ${vw} ${vh}" role="img" aria-label="${esc(title)}">
  <defs><marker id="arwA" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
    orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${t.fgMuted}"/></marker></defs>
  ${spec.grid ? `<rect width="${vw}" height="${vh}" fill="url(#g)"/>
  <defs><pattern id="g" width="40" height="40" patternUnits="userSpaceOnUse">
  <path d="M40 0 H0 V40" fill="none" stroke="${t.grid}" stroke-width="1" opacity=".5"/></pattern></defs>` : ""}
  ${layers.join("\n  ")}
</svg>
</div>
<div class="narration">
${captions.map((c, i) => `<p${i === 0 ? ' class="on"' : ""}>${esc(c.text)}</p>`).join("\n")}
</div>
<div class="abar">
  <button class="btn primary" id="areplay">Replay</button>
  <input type="range" id="abar" min="0" max="${total}" step="20" value="0" aria-label="Scrub">
</div>`;

  return {
    status: "ok",
    html: page({ title, subtitle: spec.description, theme, caption: spec.caption, css, body, script }),
    steps: steps.length,
    duration_ms: total,
  };
}
