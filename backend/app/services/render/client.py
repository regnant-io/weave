"""Client for the self-hosted visual/presentation stack.

  * render service (Node) — Vega-Lite -> SVG charts, slides -> deck HTML, Three.js
  * Gotenberg           — HTML -> PDF (deck export, reports)
  * Browserless         — HTML/SVG -> PNG (chart rasterisation for lite mode,
                          WebGL/Three.js screenshot capture)

Every produced asset is persisted to object storage and returned as a reference,
exactly like sandbox analysis outputs, so the chat surface renders them uniformly.
"""
from __future__ import annotations

import uuid

from ...config import settings
from ...storage import storage


class RenderClient:
    def __init__(self) -> None:
        import httpx
        self._httpx = httpx

    # -- capability flags -----------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(settings.render_service_url)

    @property
    def pdf_enabled(self) -> bool:
        return bool(settings.gotenberg_url)

    @property
    def raster_enabled(self) -> bool:
        # PNG rasterisation is done in-process by the render service (resvg),
        # so it's available whenever the render service is.
        return self.enabled

    # -- helpers --------------------------------------------------------------
    def _base(self) -> str:
        return (settings.render_service_url or "").rstrip("/")

    def _post(self, endpoint: str, payload: dict, timeout: float):
        """POST to the render service. Returns (response, None) or (None, error result).

        Every failure becomes a tool result the model can act on. The service
        answers a bad spec with 400 and a precise reason ("encoding refers to
        `Yield`, which is not in the data"); `raise_for_status()` turned that
        into "HTTPStatusError: 400 Bad Request", which told the model nothing
        and led to a blind rewrite of a spec that needed one word changed.
        """
        try:
            r = self._httpx.post(f"{self._base()}{endpoint}", json=payload, timeout=timeout)
        except self._httpx.TimeoutException:
            return None, {"status": "error", "code": "render_timeout", "retryable": True,
                          "error": "the render service took too long; simplify the spec "
                                   "or reduce the amount of data, then try again"}
        except self._httpx.HTTPError as exc:
            return None, {"status": "unavailable", "code": "render_unreachable",
                          "retryable": True,
                          "error": f"the render service is not reachable ({type(exc).__name__})"}
        if r.status_code < 400:
            return r, None
        message = ""
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                body = r.json()
                message = str(body.get("error") or body.get("note") or "")
            except ValueError:
                message = ""
        if r.status_code == 413:
            return None, {"status": "error", "code": "too_large", "retryable": True,
                          "error": message or "the request is too large to render; "
                                              "reduce the data or the code size"}
        if r.status_code in {429, 503}:
            return None, {"status": "error", "code": "render_busy", "retryable": True,
                          "error": "the render service is busy; try the same call again"}
        if r.status_code < 500:
            return None, {"status": "error", "code": "invalid_spec", "retryable": True,
                          "error": message or f"the renderer rejected the spec (HTTP {r.status_code})"}
        return None, {"status": "error", "code": "render_failed", "retryable": True,
                      "error": message or f"the render service failed (HTTP {r.status_code})"}

    def _save(self, data: bytes, name: str, mime: str) -> dict:
        key = f"render/{uuid.uuid4().hex[:8]}_{name}"
        storage.put_bytes(key, data)
        return {"name": name, "s3_key": key, "mime": mime, "bytes": len(data)}

    def _html_to_pdf(self, html: str) -> bytes:
        base = settings.gotenberg_url.rstrip("/")
        r = self._httpx.post(
            f"{base}/forms/chromium/convert/html",
            files={"files": ("index.html", html.encode("utf-8"), "text/html")},
            timeout=60,
        )
        r.raise_for_status()
        return r.content

    def _html_to_png(self, html: str) -> bytes:
        base = settings.browserless_url.rstrip("/")
        r = self._httpx.post(
            f"{base}/screenshot",
            json={"html": html, "options": {"type": "png", "fullPage": True}},
            timeout=60,
        )
        r.raise_for_status()
        return r.content

    # -- charts ---------------------------------------------------------------
    def chart(self, spec: dict, fmt: str = "svg", theme: str = "light") -> dict:
        import base64
        want_png = fmt == "png"
        r, error = self._post(
            "/chart", {"spec": spec, "format": "png" if want_png else "json", "theme": theme},
            timeout=30,
        )
        if error:
            return error
        body = r.json()
        svg = body.get("svg", "")
        files = [self._save(svg.encode("utf-8"), "chart.svg", "image/svg+xml")]
        # PNG for lite-mode / low-bandwidth clients (rasterised by resvg server-side).
        if want_png and body.get("png_base64"):
            files.append(self._save(base64.b64decode(body["png_base64"]), "chart.png", "image/png"))
        return {"status": "ok", "output_files": files}

    # -- decks ----------------------------------------------------------------
    def deck(self, slides: list[dict], title: str = "Weave deck", theme: str = "light",
             fmt: str = "html", subtitle: str = "") -> dict:
        if fmt == "pdf" and not self.pdf_enabled:
            return {"status": "unavailable", "code": "pdf_export_unavailable",
                    "retryable": False,
                    "error": "PDF export is unavailable in this distribution. "
                             "Use format 'html' to create the presentation."}
        r, error = self._post("/deck", {"slides": slides, "title": title,
                                        "subtitle": subtitle, "theme": theme}, timeout=30)
        if error:
            return error
        html = r.text
        files = [self._save(html.encode("utf-8"), "deck.html", "text/html")]
        if fmt == "pdf":
            pdf = self._html_to_pdf(html)
            files.append(self._save(pdf, "deck.pdf", "application/pdf"))
        return {"status": "ok", "output_files": files}

    # -- visual learning surfaces --------------------------------------------
    #
    # These four share a shape: POST a spec, get back a self-contained HTML page,
    # persist it under a STABLE key so the same visual can later be revised or
    # removed by id. The render service owns all rendering code for the first
    # three; `custom` is the escape hatch and is contained by CSP + an
    # opaque-origin iframe rather than by us vetting the code.

    def _visual(self, endpoint: str, payload: dict, *, project_id: str, visual_id: str,
                title: str, tool: str, spec: dict, source: dict | None = None) -> dict:
        from . import visuals

        # A spec the renderer rejects (bad expression, empty node list) comes back
        # as 400 with a usable message. Surfacing it verbatim lets the model
        # correct itself on the next tool call instead of silently shipping a
        # blank artifact.
        r, error = self._post(endpoint, payload, timeout=45)
        if error:
            return error
        body = r.json()
        if body.get("status") != "ok" or not body.get("html"):
            return {"status": body.get("status", "error"),
                    "error": body.get("error") or body.get("note") or "render failed"}

        saved = visuals.save(project_id, visual_id, body["html"], {
            "title": title, "kind": body.get("kind") or body.get("mode") or tool,
            "tool": tool, "spec": spec,
        }, source=source)
        return {
            "status": "ok",
            "visual_id": visual_id,
            "output_files": [{
                "name": f"{title[:48] or 'visual'}.html",
                "s3_key": saved["key"],
                "mime": "text/html",
                "bytes": len(body["html"].encode("utf-8")),
            }],
            # What the renderer adapted (e.g. a redeclared `engine`), so the
            # model learns the contract instead of repeating the habit.
            **({"adjusted": body["notes"]} if body.get("notes") else {}),
        }

    def diagram(self, spec: dict, *, project_id: str, title: str = "Diagram",
                theme: str = "light", visual_id: str | None = None) -> dict:
        from . import visuals
        vid = visual_id or visuals.new_id()
        return self._visual("/diagram", {"spec": spec, "title": title, "theme": theme},
                            project_id=project_id, visual_id=vid, title=title,
                            tool="create_diagram", spec=spec)

    def simulation(self, spec: dict, *, project_id: str, title: str = "Simulation",
                   theme: str = "light", visual_id: str | None = None) -> dict:
        from . import visuals
        vid = visual_id or visuals.new_id()
        return self._visual("/simulation", {"spec": spec, "title": title, "theme": theme},
                            project_id=project_id, visual_id=vid, title=title,
                            tool="create_simulation", spec=spec)

    def animation(self, spec: dict, *, project_id: str, title: str = "Explainer",
                  theme: str = "light", visual_id: str | None = None) -> dict:
        from . import visuals
        vid = visual_id or visuals.new_id()
        return self._visual("/animation", {"spec": spec, "title": title, "theme": theme},
                            project_id=project_id, visual_id=vid, title=title,
                            tool="create_animation", spec=spec)

    def custom(self, *, project_id: str, code: str = "", html: str = "",
               title: str = "Visual", theme: str = "light", libs: list | None = None,
               visual_id: str | None = None) -> dict:
        from . import visuals
        vid = visual_id or visuals.new_id()
        # The code and markup are the BULK, so they live in the source blob and
        # the sidecar keeps only what `list_visuals` needs to know.
        return self._visual("/custom",
                            {"code": code, "html": html, "title": title,
                             "theme": theme, "libs": libs or []},
                            project_id=project_id, visual_id=vid, title=title,
                            tool="render_custom", spec={"libs": libs or []},
                            source={"code": code, "html": html})

    def three_visual(self, scene: dict, *, project_id: str, title: str = "3D view",
                     theme: str = "dark", visual_id: str | None = None) -> dict:
        from . import visuals
        vid = visual_id or visuals.new_id()
        return self._visual("/three", {"scene": scene, "title": title, "theme": theme},
                            project_id=project_id, visual_id=vid, title=title,
                            tool="generate_3d", spec={"scene": scene})

    def babylon(self, *, project_id: str, code: str, title: str = "3D scene",
                subtitle: str = "", theme: str = "dark", assets: dict | None = None,
                controls: str = "", libs: list | None = None,
                visual_id: str | None = None) -> dict:
        """Interactive Babylon.js scene — games, 3D builders, walkthroughs.

        Assets are inlined as data URLs by the render service because the
        artifact runs with no network at all; a scene that references a URL
        would render an empty world with no explanation.
        """
        from . import visuals
        vid = visual_id or visuals.new_id()
        spec = {"controls": controls, "libs": libs or [],
                "assets": sorted((assets or {}).keys())}
        return self._visual(
            "/babylon",
            {"code": code, "title": title, "subtitle": subtitle, "theme": theme,
             "assets": assets or {}, "controls": controls, "libs": libs or []},
            project_id=project_id, visual_id=vid, title=title,
            tool="create_3d_experience", spec=spec,
            # Assets are kept alongside the code so a repair does not have to
            # re-upload a mesh the model no longer has. They are already inlined
            # in the rendered page; this is the only copy anything can EDIT.
            source={"code": code, "assets": assets or {}, "subtitle": subtitle},
        )

    def graph(self, spec: dict, *, project_id: str, title: str = "Knowledge graph",
              subtitle: str = "", theme: str = "light", visual_id: str | None = None) -> dict:
        """Node-edge knowledge graph, rendered with React Flow.

        Spec-driven: the caller supplies nodes and edges as DATA and the render
        service owns pan/zoom/layout/search/minimap. Hand-rolling that per
        request is how you end up with eight subtly different graphs.
        """
        from . import visuals
        vid = visual_id or visuals.new_id()
        return self._visual(
            "/graph",
            {"spec": spec, "title": title, "subtitle": subtitle, "theme": theme},
            project_id=project_id, visual_id=vid, title=title,
            tool="create_knowledge_graph", spec=spec,
        )

    def html_page(self, html: str, *, project_id: str, title: str = "Page",
                  strict: bool = False, visual_id: str | None = None) -> dict:
        """A complete single-file HTML page written by the model.

        The render service validates and repairs it before it is stored — see
        render-service/lib/htmlpage.js. Anything it cannot repair comes back as
        an error naming the problem, which is what lets the model fix its own
        output instead of shipping a blank page.
        """
        from . import visuals
        vid = visual_id or visuals.new_id()
        return self._visual(
            "/html", {"html": html, "title": title, "strict": strict},
            project_id=project_id, visual_id=vid, title=title,
            tool="create_html_page", spec={"bytes": len(html), "strict": bool(strict)},
            source={"html": html},
        )

    def verify_html(self, html: str) -> dict:
        """Static check that a generated page will actually open. Never stores."""
        try:
            r = self._httpx.post(f"{self._base()}/verify", json={"html": html}, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "ok": False, "errors": [str(exc)], "warnings": []}

    def engines(self) -> dict:
        """Which optional render engines this service actually has bundled.

        Advertising `create_3d_experience` when the Babylon bundle is missing
        would have the model happily build a scene that can never render.
        """
        try:
            r = self._httpx.get(f"{self._base()}/health", timeout=8)
            r.raise_for_status()
            return r.json().get("engines", {}) or {}
        except Exception:  # noqa: BLE001 - unreachable service: assume nothing
            return {}

    # -- 3D -------------------------------------------------------------------
    def three(self, scene: dict, title: str = "Weave 3D", capture: bool = False) -> dict:
        r = self._httpx.post(f"{self._base()}/three", json={"scene": scene, "title": title},
                             timeout=30)
        r.raise_for_status()
        payload = r.json()
        html = payload.get("html", "")
        files = []
        if html:
            files.append(self._save(html.encode("utf-8"), "scene.html", "text/html"))
            # WebGL snapshot needs a real GPU-capable browser (Browserless); resvg
            # can't rasterise WebGL. Skip cleanly when Browserless isn't configured.
            if capture and settings.browserless_url:
                png = self._html_to_png(html)
                files.append(self._save(png, "scene.png", "image/png"))
        return {"status": payload.get("status", "ok"), "output_files": files,
                "note": payload.get("note", "")}


_client: RenderClient | None = None


def get_render() -> RenderClient:
    global _client
    if _client is None:
        _client = RenderClient()
    return _client
