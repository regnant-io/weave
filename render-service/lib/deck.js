// Slide decks that look designed rather than dumped.
//
// The previous renderer produced an unstyled `<section>` per slide, hard-coded a
// teal heading colour that appears nowhere in the design system, and ran the
// slide body through a five-line regex "markdown" that mangled anything it did
// not recognise. The result was technically a deck and visibly a draft.
//
// What actually makes a generated deck look designed is not more decoration —
// it is consistency and restraint:
//
//   * ONE typographic hierarchy, shared with the rest of Weave (one grotesque
//     display, sans for body, mono for labels).
//   * A LAYOUT PER SLIDE SHAPE. A section divider, a statement, a two-column
//     comparison and a data slide want different geometry; giving them all the
//     same top-left stack is what makes decks look automated.
//   * Generous, consistent margins and a real baseline rhythm.
//   * Chrome that stays out of the way: slide numbers and progress, no
//     watermark, no gradient.
//
// Output is one self-contained HTML file — no CDN, no external font, keyboard
// and touch navigation, and a print stylesheet so "export to PDF" works from
// the browser without a second service.

import { esc, baseCss, palette } from "./theme.js";

/**
 * Inline markdown for slide bodies.
 *
 * Deliberately small but CORRECT for what it claims to support, and it escapes
 * first so a stray `<` in the model's text can never inject markup.
 */
function inline(md) {
  return esc(md)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>");
}

/** Block-level markdown: headings, lists, blockquotes, paragraphs. */
function body(md) {
  const lines = String(md || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let list = null; // "ul" | "ol"
  let para = [];

  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${inline(para.join(" "))}</p>`);
      para = [];
    }
  };
  const flushList = () => {
    if (list) {
      out.push(`</${list}>`);
      list = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushPara();
      flushList();
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      flushPara();
      flushList();
      out.push(`<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      flushPara();
      flushList();
      out.push(`<blockquote>${inline(line.replace(/^>\s?/, ""))}</blockquote>`);
      continue;
    }
    const ul = /^[-*+]\s+(.*)$/.exec(line);
    const ol = /^\d+[.)]\s+(.*)$/.exec(line);
    if (ul || ol) {
      flushPara();
      const kind = ul ? "ul" : "ol";
      if (list !== kind) {
        flushList();
        out.push(`<${kind}>`);
        list = kind;
      }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      continue;
    }
    flushList();
    para.push(line);
  }
  flushPara();
  flushList();
  return out.join("\n");
}

/**
 * Pick a layout for a slide.
 *
 * Explicit `layout` wins; otherwise it is inferred from the slide's own shape.
 * Inference matters because a model reliably supplies title/body and rarely
 * remembers a layout field, and a deck where every slide has identical geometry
 * is the single clearest tell that nobody designed it.
 */
function layoutFor(slide, index) {
  const explicit = String(slide.layout || "").toLowerCase();
  const allowed = ["title", "section", "statement", "bullets", "split", "quote", "data", "end"];
  if (allowed.includes(explicit)) return explicit;

  const text = String(slide.body_md || "").trim();
  if (index === 0 && !text) return "title";
  if (!text) return "section";
  if (slide.left || slide.right) return "split";
  if (/^>/.test(text)) return "quote";
  if (slide.metrics && slide.metrics.length) return "data";
  if (text.length < 130 && !/^[-*+\d]/m.test(text)) return "statement";
  return "bullets";
}

function renderSlide(slide, index, total, colors) {
  const layout = layoutFor(slide, index);
  const title = slide.title ? esc(slide.title) : "";
  const eyebrow = slide.eyebrow ? esc(slide.eyebrow) : "";
  const content = body(slide.body_md || "");

  if (layout === "title") {
    return `<section class="s-title">
      ${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}
      <h1>${title}</h1>
      ${content ? `<div class="lede">${content}</div>` : ""}
      <div class="rule-accent"></div>
    </section>`;
  }

  if (layout === "section") {
    return `<section class="s-section">
      <div class="num">${String(index + 1).padStart(2, "0")}</div>
      <h2>${title}</h2>
      ${content ? `<div class="lede">${content}</div>` : ""}
    </section>`;
  }

  if (layout === "statement") {
    return `<section class="s-statement">
      ${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}
      ${title ? `<h2>${title}</h2>` : ""}
      <div class="big">${content}</div>
    </section>`;
  }

  if (layout === "quote") {
    return `<section class="s-quote">
      <div class="mark">&ldquo;</div>
      <div class="big">${content}</div>
      ${title ? `<div class="attrib">— ${title}</div>` : ""}
    </section>`;
  }

  if (layout === "split") {
    return `<section class="s-split">
      ${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}
      ${title ? `<h2>${title}</h2>` : ""}
      <div class="cols">
        <div class="col">${body(slide.left || slide.body_md || "")}</div>
        <div class="col">${body(slide.right || "")}</div>
      </div>
    </section>`;
  }

  if (layout === "data") {
    const metrics = (slide.metrics || []).slice(0, 4).map((m, i) => `
      <div class="metric">
        <div class="mv" style="color:${colors[i % colors.length]}">${esc(m.value ?? "")}</div>
        <div class="ml">${esc(m.label ?? "")}</div>
        ${m.note ? `<div class="mn">${esc(m.note)}</div>` : ""}
      </div>`).join("");
    return `<section class="s-data">
      ${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}
      ${title ? `<h2>${title}</h2>` : ""}
      <div class="metrics">${metrics}</div>
      ${content ? `<div class="note">${content}</div>` : ""}
    </section>`;
  }

  if (layout === "end") {
    return `<section class="s-title">
      <h1>${title || "Asante / Thank you"}</h1>
      ${content ? `<div class="lede">${content}</div>` : ""}
      <div class="rule-accent"></div>
    </section>`;
  }

  return `<section class="s-bullets">
    ${eyebrow ? `<div class="eyebrow">${eyebrow}</div>` : ""}
    ${title ? `<h2>${title}</h2>` : ""}
    <div class="content">${content}</div>
  </section>`;
}

export function renderDeck({ slides = [], title = "Weave deck", subtitle = "", theme = "light" }) {
  if (!Array.isArray(slides) || !slides.length) {
    return { status: "error", error: "no slides supplied" };
  }
  const colors = palette(theme);
  const total = slides.length;
  const sections = slides.map((s, i) => renderSlide(s || {}, i, total, colors)).join("\n");

  const css = `
.deck{position:fixed;inset:0;overflow:hidden}
section{position:absolute;inset:0;display:none;flex-direction:column;justify-content:center;
  padding:8vh 9vw;box-sizing:border-box}
section.active{display:flex;animation:slideIn .42s cubic-bezier(.16,1,.3,1) both}
@keyframes slideIn{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}

h1{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;font-size:clamp(34px,6.4vw,74px);font-weight:600;
  line-height:1.04;letter-spacing:-.028em;margin:.12em 0 0}
h2{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;font-size:clamp(25px,3.9vw,44px);font-weight:600;
  line-height:1.12;letter-spacing:-.022em;margin:.1em 0 .5em}
h3{font-size:clamp(16px,1.7vw,20px);font-weight:600;margin:1.1em 0 .35em;letter-spacing:-.01em}
h4,h5{font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--fg-muted);
  font-weight:600;margin:1.2em 0 .4em}
p,li{font-size:clamp(15px,1.65vw,20px);line-height:1.62;color:var(--fg-muted)}
p{margin:0 0 .8em;max-width:62ch}
ul,ol{margin:0 0 .8em;padding-left:1.15em;max-width:62ch}
li{margin:.42em 0}
li::marker{color:var(--accent)}
strong{color:var(--fg);font-weight:650}
code{font-family:ui-monospace,Consolas,monospace;font-size:.86em;background:var(--surface-2);
  border:1px solid var(--border);padding:.08em .34em}
blockquote{margin:.6em 0;padding-left:1em;border-left:2px solid var(--accent);
  font-style:italic;color:var(--fg-muted)}
.rule-accent{height:2px;background:var(--accent);width:88px;margin-top:2.2rem}

.s-title .lede,.s-section .lede{max-width:56ch;margin-top:1.1rem}
.s-section .num{font-family:ui-monospace,Consolas,monospace;font-size:13px;color:var(--accent);
  letter-spacing:.14em;margin-bottom:.7rem}
.s-statement .big,.s-quote .big{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
  font-size:clamp(24px,3.6vw,42px);line-height:1.28;letter-spacing:-.018em;color:var(--fg);max-width:22ch}
.s-statement .big p,.s-quote .big p{font-size:inherit;line-height:inherit;color:inherit;max-width:none}
.s-quote{align-items:flex-start}
.s-quote .mark{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;font-size:76px;line-height:.6;color:var(--accent);opacity:.5}
.s-quote .attrib{margin-top:1.6rem;font-size:14px;color:var(--fg-faint);letter-spacing:.02em}
.s-split .cols{display:grid;grid-template-columns:1fr 1fr;gap:3.2rem;align-items:start}
.s-split .col p,.s-split .col ul{max-width:none}
.s-data .metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));
  gap:1.6rem;margin:.6rem 0 1.4rem}
.s-data .mv{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,Roboto,sans-serif;font-size:clamp(30px,4.4vw,54px);font-weight:600;
  letter-spacing:-.03em;line-height:1}
.s-data .ml{font-size:13px;color:var(--fg-muted);margin-top:.35rem;line-height:1.4}
.s-data .mn{font-size:11.5px;color:var(--fg-faint);margin-top:.2rem}
.s-data .note{border-top:1px solid var(--border);padding-top:1rem}

.chrome{position:fixed;left:0;right:0;bottom:0;height:34px;display:flex;align-items:center;
  gap:14px;padding:0 9vw;font-family:ui-monospace,Consolas,monospace;font-size:11px;
  color:var(--fg-faint);letter-spacing:.08em;pointer-events:none}
.chrome .bar{flex:1;height:1px;background:var(--border);position:relative}
.chrome .bar i{position:absolute;left:0;top:0;bottom:0;background:var(--accent);
  transition:width .42s cubic-bezier(.16,1,.3,1)}
.hint{position:fixed;right:9vw;top:22px;font-size:11px;color:var(--fg-faint);
  opacity:.7;pointer-events:none}

@media (max-width:720px){
  section{padding:6vh 7vw}
  .s-split .cols{grid-template-columns:1fr;gap:1.4rem}
}
/* Browser "Print to PDF" produces a real deck: one slide per landscape page. */
@media print{
  @page{size:landscape;margin:0}
  .deck{position:static}
  section{position:relative;display:flex!important;height:100vh;page-break-after:always;
    animation:none}
  .chrome,.hint{display:none}
}`;

  const script = `
var slides=[].slice.call(document.querySelectorAll('section'));
var idx=0, bar=document.querySelector('.chrome .bar i'), pos=document.querySelector('.chrome .pos');
function show(n){
  idx=Math.max(0,Math.min(slides.length-1,n));
  slides.forEach(function(s,i){ s.classList.toggle('active', i===idx); });
  if(bar) bar.style.width=(((idx+1)/slides.length)*100)+'%';
  if(pos) pos.textContent=(idx+1)+' / '+slides.length;
  try{ location.hash='s'+(idx+1); }catch(e){}
}
document.addEventListener('keydown',function(e){
  if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' ') { e.preventDefault(); show(idx+1); }
  if(e.key==='ArrowLeft'||e.key==='PageUp') { e.preventDefault(); show(idx-1); }
  if(e.key==='Home') show(0);
  if(e.key==='End') show(slides.length-1);
});
// Touch: a deck is read on phones as often as projected.
var x0=null;
document.addEventListener('touchstart',function(e){ x0=e.touches[0].clientX; },{passive:true});
document.addEventListener('touchend',function(e){
  if(x0===null) return;
  var dx=e.changedTouches[0].clientX-x0;
  if(Math.abs(dx)>48) show(idx+(dx<0?1:-1));
  x0=null;
},{passive:true});
document.addEventListener('click',function(e){
  if(e.target.closest('a')) return;
  show(idx + (e.clientX > window.innerWidth*0.62 ? 1 : e.clientX < window.innerWidth*0.38 ? -1 : 1));
});
var m=/^#s(\\d+)$/.exec(location.hash||'');
show(m?parseInt(m[1],10)-1:0);
`;

  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>${baseCss(theme)}${css}</style></head>
<body>
<div class="deck">${sections}</div>
<div class="hint">← → or tap</div>
<div class="chrome"><span class="pos">1 / ${total}</span><span class="bar"><i></i></span>
<span>${esc(subtitle || title)}</span></div>
<script>${script}</script>
</body></html>`;

  return { status: "ok", html, slides: total };
}
