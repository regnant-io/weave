"""Run a generated artifact in a real browser and report what actually happened.

WHY THIS EXISTS
---------------
`lib/js.js::lintHtml` is a STATIC check. It catches the failures that are
visible in the source — an `import` in a classic script, a CDN `<script src>`,
a file truncated mid-function. It cannot catch the failure that dominates in
practice:

    Scene error: createScene did not return a BABYLON.Scene

That page is perfectly well-formed. Every tag balances, nothing loads from the
network, the lint passes cleanly — and it renders a black rectangle, because the
model wrote `const scene = new BABYLON.Scene(engine)` and forgot to return it.
The only way to know is to RUN IT.

So this module opens the artifact in the Browserless Chromium pool that the deep
profile already runs, lets it boot, and reports:

  * uncaught exceptions and unhandled rejections (`pageerror`),
  * `console.error` output,
  * requests to the network (an artifact has none, so any attempt is a defect),
  * the text of the `#err` panel, which is where every Weave renderer surfaces a
    scene/setup failure to the human,
  * whether anything was actually PAINTED — text, a non-empty canvas, or SVG.
    A page that throws nothing and draws nothing is still broken.
  * a JPEG screenshot, which is both the evidence and (for a vision-capable
    model) something to critique.

The findings come back in a shape the model can act on. "It renders blank" is
not actionable; "createScene did not return a BABYLON.Scene" is.

Failure of the PROBE ITSELF is never treated as failure of the artifact. If
Browserless is not configured or is down, `available` is False and the caller
falls back to the static lint — degrading to the old behaviour rather than
blocking delivery of work that is probably fine.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from ...config import settings

log = logging.getLogger("weave.probe")

#: How long to let a page boot before judging it. A Babylon scene compiles
#: shaders and uploads geometry; judging it at 200ms would fail every 3D
#: artifact for being slow rather than broken.
DEFAULT_SETTLE_MS = 1400
HEAVY_SETTLE_MS = 3200

#: Console noise that is not a defect. Chromium emits these for pages that are
#: behaving exactly as designed inside an opaque-origin sandbox.
_IGNORABLE = (
    "download the react devtools",
    "favicon.ico",
    "was preloaded using link preload",
    "sandboxed and the 'allow-scripts' permission is not set",
    "third-party cookie",
    # Duplicated by `failedResources`, which knows the URL. The bare console
    # form names nothing, so it cannot be acted on and cannot be filtered.
    "failed to load resource",
)

#: The in-page script. Kept as one string rather than assembled, because a
#: syntax error here fails EVERY probe and is far easier to spot in one block.
_PROBE_JS = r"""
export default async function ({ page, context }) {
  const consoleErrors = [];
  const pageErrors = [];
  const networkAttempts = [];
  const failedResources = [];

  page.on('console', (m) => {
    const t = m.type();
    if (t === 'error' || t === 'warning') {
      consoleErrors.push({ level: t, text: String(m.text()).slice(0, 600) });
    }
  });
  page.on('pageerror', (e) => {
    pageErrors.push(String((e && e.message) || e).slice(0, 600));
  });
  page.on('request', (r) => {
    const u = r.url();
    if (/^https?:/i.test(u)) networkAttempts.push(u.slice(0, 300));
  });
  page.on('requestfailed', (r) => {
    const u = r.url();
    if (/^https?:/i.test(u)) networkAttempts.push(u.slice(0, 300));
  });
  // Chromium logs "Failed to load resource: ... 404" to the console with no URL
  // attached, which is unactionable and — for a favicon nobody asked for —
  // simply wrong. Watching responses gives us the URL, so the caller can tell a
  // missing script from a missing favicon.
  page.on('response', (r) => {
    try {
      if (r.status() >= 400) {
        failedResources.push({ url: String(r.url()).slice(0, 300), status: r.status() });
      }
    } catch (e) {}
  });

  await page.setViewport({ width: context.width || 1100, height: context.height || 720 });

  try {
    // Two entry points, one set of checks: `html` for an artifact (a single
    // self-contained document) and `url` for a dev server the workspace is
    // running. Everything after this line is identical, because "did it throw"
    // and "did anything paint" mean the same thing either way.
    if (context.url) {
      await page.goto(context.url, { waitUntil: 'domcontentloaded', timeout: 25000 });
    } else {
      await page.setContent(context.html, { waitUntil: 'domcontentloaded', timeout: 20000 });
    }
  } catch (e) {
    return {
      data: {
        loaded: false,
        loadError: String((e && e.message) || e).slice(0, 400),
        consoleErrors, pageErrors, networkAttempts, failedResources,
      },
      type: 'application/json',
    };
  }

  // Wait for the page to SAY it is ready rather than sleeping a fixed amount.
  //
  // Every Weave renderer shows a `#boot` overlay and adds `.gone` once it has
  // painted real frames, and reveals `#err` when setup failed. Watching for
  // either means a scene that boots in 400ms costs 400ms instead of the three
  // seconds a 3D page might need in the worst case — and a genuinely slow scene
  // still gets its full budget. Pages with no such markers (a plain HTML
  // document) fall through to the fixed settle, which is what they need anyway.
  const budget = context.settleMs || 1400;
  try {
    await page.waitForFunction(
      () => {
        const err = document.getElementById('err');
        if (err && (err.textContent || '').trim()) {
          const cs = window.getComputedStyle(err);
          if (cs.display !== 'none' && cs.visibility !== 'hidden') return true;
        }
        const boot = document.getElementById('boot');
        if (boot) return boot.classList.contains('gone');
        return null;   // no readiness marker — keep polling until the budget ends
      },
      { timeout: budget, polling: 100 },
    );
    // A short grace period so the frame that proves it works is on screen
    // before the screenshot is taken.
    await new Promise((r) => setTimeout(r, 260));
  } catch (e) {
    // Budget expired with no signal. That is not itself a failure — the paint
    // checks below decide.
  }

  // What the page actually put on screen, and what it told the human.
  const paint = await page.evaluate(() => {
    const out = {
      textLen: 0, canvases: 0, paintedCanvases: 0, svgs: 0,
      elements: 0, bodyHeight: 0,
      visibleError: '', title: document.title || '',
    };
    try { out.textLen = ((document.body && document.body.innerText) || '').trim().length; } catch (e) {}
    try { out.svgs = document.querySelectorAll('svg').length; } catch (e) {}
    // Text length alone is a bad blankness test: a working counter app renders
    // "0" and "+1", which is four characters. What distinguishes a blank page is
    // that it has no laid-out content at all.
    try {
      out.elements = document.body ? document.body.querySelectorAll('*').length : 0;
      out.bodyHeight = document.body
        ? Math.round(document.body.getBoundingClientRect().height) : 0;
    } catch (e) {}

    // Every Weave renderer surfaces a setup failure into #err and reveals it.
    //
    // Visibility is tested with getComputedStyle, NOT offsetParent: the error
    // panel is `position: fixed`, and offsetParent is null for fixed elements
    // even when they are plainly on screen. That one wrong predicate made this
    // probe miss the single most common Babylon failure — a scene function that
    // builds everything correctly and forgets `return scene;` — because the
    // page reports it perfectly and we were not reading the report.
    try {
      for (const el of document.querySelectorAll('#err, .weave-error, [data-weave-error]')) {
        const txt = String(el.textContent || '').trim();
        if (!txt) continue;
        const cs = window.getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
        out.visibleError = txt.slice(0, 600);
        break;
      }
    } catch (e) {}

    // A canvas that was never drawn into is byte-identical to a blank one of
    // the same size. WebGL contexts without preserveDrawingBuffer read back
    // blank even when they painted, so this is reported, never asserted.
    try {
      const list = Array.from(document.querySelectorAll('canvas'));
      out.canvases = list.length;
      for (const c of list) {
        if (!c.width || !c.height) continue;
        try {
          const blank = document.createElement('canvas');
          blank.width = c.width; blank.height = c.height;
          if (c.toDataURL() !== blank.toDataURL()) out.paintedCanvases += 1;
        } catch (e) {
          out.paintedCanvases += 1;  // tainted canvas == something was drawn
        }
      }
    } catch (e) {}
    return out;
  });

  let screenshot = '';
  try {
    screenshot = await page.screenshot({ encoding: 'base64', type: 'jpeg', quality: 62 });
  } catch (e) { /* a screenshot failure is not an artifact failure */ }

  return {
    data: { loaded: true, consoleErrors, pageErrors, networkAttempts,
            failedResources, paint, screenshot },
    type: 'application/json',
  };
}
"""


@dataclass
class ProbeResult:
    """What running the artifact actually produced."""

    available: bool = True          # False = the probe could not run at all
    ok: bool = False
    errors: list[str] = field(default_factory=list)     # defects: must be fixed
    warnings: list[str] = field(default_factory=list)   # worth knowing, not fatal
    screenshot_b64: str = ""
    title: str = ""
    #: Raw signals, kept so a caller can make its own judgement.
    paint: dict = field(default_factory=dict)
    duration_ms: int = 0
    note: str = ""

    def as_tool_result(self) -> dict:
        """The shape handed back to the model. Deliberately blunt."""
        out = {
            "ran": self.available,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if not self.available:
            out["note"] = self.note or "the artifact could not be executed on this server"
        elif self.ok:
            out["note"] = "The page opened and rendered without errors."
        else:
            out["note"] = (
                "This page is BROKEN as written. Fix the errors listed above and "
                "call the tool again — do not present it to the user until it opens clean."
            )
        return out

    def summary(self) -> str:
        """One line for a step chip."""
        if not self.available:
            return "not executed"
        if self.ok:
            return "renders clean" + (f" · {len(self.warnings)} warnings" if self.warnings else "")
        return f"{len(self.errors)} runtime " + ("error" if len(self.errors) == 1 else "errors")


class ArtifactProbe:
    """Executes artifact HTML in the Browserless Chromium pool."""

    def __init__(self) -> None:
        import httpx

        self._httpx = httpx

    @property
    def enabled(self) -> bool:
        return bool(settings.browserless_url)

    def run(self, html: str, *, heavy: bool = False, settle_ms: int | None = None) -> ProbeResult:
        """Open `html` in a real browser and report what happened.

        `heavy` means a 3D / WebGL / simulation page, which needs longer to boot
        before "nothing has been painted" means anything.
        """
        import time

        if not self.enabled:
            return ProbeResult(available=False, ok=True, note="Browserless is not configured")
        if not (html or "").strip():
            return ProbeResult(ok=False, errors=["the document is empty"])

        settle = int(settle_ms or (HEAVY_SETTLE_MS if heavy else DEFAULT_SETTLE_MS))
        base = (settings.browserless_url or "").rstrip("/")
        started = time.monotonic()
        try:
            resp = self._httpx.post(
                f"{base}/function",
                json={"code": _PROBE_JS,
                      "context": {"html": html, "settleMs": settle,
                                  "width": 1100, "height": 720}},
                # The settle time is inside the browser, so the HTTP timeout has
                # to exceed it with room for Chromium startup under load.
                timeout=(settle / 1000.0) + 45.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - a probe outage must not block delivery
            # Logged at WARNING, with the message: a silently-degrading verifier
            # is indistinguishable from one that passes everything, which is the
            # worst possible failure mode for a gate.
            log.warning("artifact probe could not run (%s): %s", type(exc).__name__, exc)
            return ProbeResult(
                available=False, ok=True,
                duration_ms=int((time.monotonic() - started) * 1000),
                note=f"could not reach the browser pool ({type(exc).__name__}: {exc})"[:300],
            )

        data = payload.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}

        result = self._interpret(data, heavy=heavy)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    def run_url(self, url: str, *, heavy: bool = False,
                settle_ms: int | None = None) -> ProbeResult:
        """Same checks, against a URL the browser navigates to.

        For dev servers rather than artifacts. The two differ in exactly one
        respect that matters here: a served app is ALLOWED to make network
        requests, so the caller filters that finding out. Everything else — an
        exception, a console error, a page that painted nothing — means the same
        thing whether the HTML arrived inline or over HTTP.
        """
        import time

        if not self.enabled:
            return ProbeResult(available=False, ok=True, note="Browserless is not configured")
        if not (url or "").strip():
            return ProbeResult(ok=False, errors=["no URL to open"])

        settle = int(settle_ms or (HEAVY_SETTLE_MS if heavy else DEFAULT_SETTLE_MS))
        base = (settings.browserless_url or "").rstrip("/")
        started = time.monotonic()
        try:
            resp = self._httpx.post(
                f"{base}/function",
                json={"code": _PROBE_JS,
                      "context": {"url": url, "settleMs": settle,
                                  "width": 1280, "height": 800}},
                timeout=(settle / 1000.0) + 45.0,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("preview probe could not run (%s): %s", type(exc).__name__, exc)
            return ProbeResult(available=False, ok=True,
                               duration_ms=int((time.monotonic() - started) * 1000),
                               note=f"could not reach the browser pool ({type(exc).__name__})")

        data = payload.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        result = self._interpret(data, heavy=heavy, allow_network=True)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    # -- judgement ---------------------------------------------------------

    @staticmethod
    def _interpret(data: dict, *, heavy: bool, allow_network: bool = False) -> ProbeResult:
        errors: list[str] = []
        warnings: list[str] = []

        if not data.get("loaded", False):
            msg = data.get("loadError") or "the page did not load"
            return ProbeResult(ok=False, errors=[f"the document failed to load: {msg}"])

        paint = data.get("paint") or {}

        # 1. The renderer's own error panel. This is the single most useful
        #    signal we have: it is the exact text a human would see on screen.
        visible = str(paint.get("visibleError") or "").strip()
        if visible:
            errors.append(visible if visible.lower().startswith("scene error")
                          else f"the page displayed an error: {visible}")

        # 2. Uncaught exceptions. Anything that reaches `pageerror` stopped a
        #    script dead partway through.
        for msg in data.get("pageErrors") or []:
            text = str(msg).strip()
            if text and not _ignorable(text):
                errors.append(f"uncaught exception: {text}")

        # 3. console.error is how a page reports a failure it caught itself.
        for entry in data.get("consoleErrors") or []:
            text = str(entry.get("text") or "").strip()
            if not text or _ignorable(text):
                continue
            if entry.get("level") == "error":
                errors.append(f"console error: {text}")
            else:
                warnings.append(f"console warning: {text}")

        # 4. The artifact sandbox has no network. A request proves the page
        #    depends on something it will never get.
        # 4. An ARTIFACT has no network, so a request proves it depends on
        #    something it will never get. A dev server obviously does have one,
        #    and the same finding there is just traffic.
        network = list(dict.fromkeys(data.get("networkAttempts") or []))
        if network and not allow_network:
            errors.append(
                "this page requests external URLs, which are blocked in the artifact "
                "sandbox — inline them instead: " + ", ".join(network[:4])
            )

        # 4b. Resources the page asked for and did not get. Reported with the
        #     URL, which is the difference between "something 404'd" and "your
        #     app.js is missing". A favicon nobody requested is not a defect and
        #     is the single most common false positive here.
        for res in data.get("failedResources") or []:
            url = str(res.get("url") or "")
            if not url or "favicon" in url.lower():
                continue
            errors.append(
                f"the page requested {url.rsplit('/', 1)[-1] or url} and got "
                f"HTTP {res.get('status')} — that file is missing or the path is wrong"
            )

        # 5. Nothing thrown, nothing drawn. A silently blank page is still a
        #    failed artifact, and it is the one the model is most confident about.
        text_len = int(paint.get("textLen") or 0)
        canvases = int(paint.get("canvases") or 0)
        painted = int(paint.get("paintedCanvases") or 0)
        svgs = int(paint.get("svgs") or 0)
        elements = int(paint.get("elements") or 0)
        body_height = int(paint.get("bodyHeight") or 0)
        # A minimal page is not a blank one. A working counter renders "0" and
        # "+1" — four characters — and an earlier `text_len > 12` threshold
        # called that "rendered nothing at all", which would send the model off
        # to repair something that was already correct. Laid-out content is the
        # signal that actually distinguishes the two.
        drew_something = (
            text_len > 0 or svgs > 0 or painted > 0
            or (elements >= 3 and body_height > 8)
        )

        if not drew_something:
            if canvases and not painted:
                # A WebGL context without preserveDrawingBuffer reads back blank
                # even when it painted correctly, so this cannot be asserted.
                (errors if not heavy else warnings).append(
                    "the page rendered no visible content: it has a canvas but nothing "
                    "was drawn into it, and there is no text or SVG on the page"
                )
            else:
                errors.append(
                    "the page rendered nothing at all — no text, no SVG and no canvas "
                    "content. Check that your setup code actually runs and appends to "
                    "the document."
                )
        elif canvases and not painted and heavy:
            warnings.append("the canvas read back blank; if the scene looks empty, "
                            "check that a camera and a light were added")

        return ProbeResult(
            ok=not errors,
            errors=errors[:12],
            warnings=warnings[:8],
            screenshot_b64=str(data.get("screenshot") or ""),
            title=str(paint.get("title") or ""),
            paint=paint,
        )


def _ignorable(text: str) -> bool:
    low = text.lower()
    return any(frag in low for frag in _IGNORABLE)


_probe: ArtifactProbe | None = None


def get_probe() -> ArtifactProbe:
    global _probe
    if _probe is None:
        _probe = ArtifactProbe()
    return _probe
