"""Visual-learning tools: create, revise, remove, and present.

Two things separate this from a plain "make a chart" tool:

  * CRUD. The model can list what it has already produced in this project and
    revise it in place. Without that, an iterative session accumulates a dozen
    near-duplicate artifacts and the user has to work out which is current.

  * Mid-run presentation. A run that takes an hour must be able to show its
    working before it finishes. `present_visual` pushes an artifact into the
    transcript the moment it exists, rather than at the end of the turn.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry


def _render(ctx: ToolContext):
    client = ctx.services.get("render")
    if client is None or not client.enabled:
        return None
    return client


def _unavailable() -> dict:
    return {"status": "unavailable",
            "message": "the render service is not configured (WEAVE_RENDER_URL)"}


def _project_id(ctx: ToolContext) -> str:
    return getattr(ctx.project, "id", "shared")


def _emit_artifacts(ctx: ToolContext, result: dict, title: str) -> None:
    """Push finished artifacts into the live transcript immediately.

    The orchestrator also collects artifacts at the end of the turn, but a long
    agentic run should not make the user wait for the whole thing to finish
    before seeing a chart it produced twenty minutes ago.
    """
    from ...security import sign_path

    for f in result.get("output_files", []) or []:
        key = f.get("s3_key")
        if not key:
            continue
        ctx.progress("artifact", {
            "name": f.get("name") or title,
            "mime": f.get("mime", "text/html"),
            "bytes": f.get("bytes", 0),
            "tool": result.get("tool", ""),
            "visual_id": result.get("visual_id"),
            "url": f"/api/artifact/{key}?sig={sign_path(key)}",
        })


# --- creation --------------------------------------------------------------

def _create_diagram(ctx: ToolContext, inp: dict) -> dict:
    client = _render(ctx)
    if not client:
        return _unavailable()
    title = str(inp.get("title") or "Diagram")
    out = client.diagram(inp.get("spec") or {}, project_id=_project_id(ctx),
                         title=title, theme=inp.get("theme", "light"))
    out["tool"] = "create_diagram"
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


def _create_simulation(ctx: ToolContext, inp: dict) -> dict:
    client = _render(ctx)
    if not client:
        return _unavailable()
    title = str(inp.get("title") or "Simulation")
    out = client.simulation(inp.get("spec") or {}, project_id=_project_id(ctx),
                            title=title, theme=inp.get("theme", "light"))
    out["tool"] = "create_simulation"
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


def _create_animation(ctx: ToolContext, inp: dict) -> dict:
    client = _render(ctx)
    if not client:
        return _unavailable()
    title = str(inp.get("title") or "Explainer")
    out = client.animation(inp.get("spec") or {}, project_id=_project_id(ctx),
                           title=title, theme=inp.get("theme", "light"))
    out["tool"] = "create_animation"
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


def _create_knowledge_graph(ctx: ToolContext, inp: dict) -> dict:
    client = _render(ctx)
    if not client:
        return _unavailable()
    title = str(inp.get("title") or "Knowledge graph")
    out = client.graph(inp.get("spec") or {}, project_id=_project_id(ctx), title=title,
                       subtitle=str(inp.get("subtitle") or ""),
                       theme=inp.get("theme", "light"))
    out["tool"] = "create_knowledge_graph"
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


def _create_html_page(ctx: ToolContext, inp: dict) -> dict:
    client = _render(ctx)
    if not client:
        return _unavailable()
    title = str(inp.get("title") or "Page")
    html = str(inp.get("html") or "")
    out = client.html_page(html, project_id=_project_id(ctx), title=title,
                           strict=bool(inp.get("strict")))
    out["tool"] = "create_html_page"
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


def _verify_artifact(ctx: ToolContext, inp: dict) -> dict:
    """Check a page opens BEFORE it is handed over.

    Two passes, because they catch different things:

      * the STATIC lint reads the source and finds what is visibly wrong — ESM
        syntax in a classic script, a CDN `<script src>`, a truncated file;
      * the LIVE run opens the page in a real browser and finds what is only
        discoverable by executing it. This is the pass that catches
        "createScene did not return a BABYLON.Scene", which is a perfectly
        well-formed document that renders a black rectangle.

    Artifacts produced by the tools are gated automatically (see
    services/orchestration/verification.py), so this tool is for pages the model
    has written but not yet submitted — checking a draft, or a page it read out
    of the workspace.
    """
    client = _render(ctx)
    if not client:
        return _unavailable()
    html = str(inp.get("html") or "")
    source = "supplied html"
    if not html.strip():
        vid = str(inp.get("visual_id") or "")
        path = str(inp.get("workspace_path") or "")
        if vid:
            from ..render import visuals
            html = visuals.load_html(_project_id(ctx), vid)
            source = f"visual {vid}"
        elif path:
            # Checking a page the model built in the workspace is the same
            # question, and refusing to answer it just because the file lives
            # somewhere else would send the model back to guessing.
            workspace = ctx.services.get("workspace")
            if workspace is None:
                return {"status": "error",
                        "error": "the workspace is not available on this server"}
            read = workspace.read_file(_project_id(ctx), path)
            if read.get("status") != "ok":
                return {"status": "error", "error": read.get("error") or "could not read the file"}
            html = read.get("content") or ""
            source = path
        if not html.strip():
            return {"status": "error",
                    "error": "supply `html`, a `visual_id`, or a `workspace_path` that exists"}

    static = client.verify_html(html)
    errors = [str(e) for e in (static.get("errors") or [])]
    warnings = [str(w) for w in (static.get("warnings") or [])]

    from ..render.probe import get_probe
    run = get_probe().run(html, heavy=bool(inp.get("heavy", True)))
    if run.available:
        errors += run.errors
        warnings += run.warnings

    ok = not errors
    return {
        "status": "ok",
        "tool": "verify_artifact",
        "checked": source,
        "executed": run.available,
        "ok": ok,
        "errors": errors[:12],
        "warnings": warnings[:8],
        "note": (
            "The page opens and renders without errors."
            if ok else
            "This page is BROKEN. Fix the errors listed and check it again before "
            "showing it to the user."
        ),
    }


def _render_custom(ctx: ToolContext, inp: dict) -> dict:
    client = _render(ctx)
    if not client:
        return _unavailable()
    title = str(inp.get("title") or "Visual")
    out = client.custom(project_id=_project_id(ctx), code=str(inp.get("code") or ""),
                        html=str(inp.get("html") or ""), title=title,
                        theme=inp.get("theme", "light"), libs=inp.get("libs") or [])
    out["tool"] = "render_custom"
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


# --- CRUD ------------------------------------------------------------------

def _list_visuals(ctx: ToolContext, _inp: dict) -> dict:
    from ..render import visuals
    return {"status": "ok", "visuals": visuals.listing(_project_id(ctx))}


def _update_visual(ctx: ToolContext, inp: dict) -> dict:
    """Re-render an existing visual in place, keeping its id and URL."""
    from ..render import visuals

    client = _render(ctx)
    if not client:
        return _unavailable()
    vid = str(inp.get("visual_id") or "")
    pid = _project_id(ctx)
    rec = visuals.load_meta(pid, vid)
    if not rec:
        return {"status": "error", "error": f"no visual with id {vid!r} in this project"}

    tool = rec.get("tool")
    title = str(inp.get("title") or rec.get("title") or "Visual")
    spec = visuals.merge_spec(rec.get("spec") or {}, inp.get("spec") or {})
    theme = inp.get("theme", "light")

    if tool == "create_diagram":
        out = client.diagram(spec, project_id=pid, title=title, theme=theme, visual_id=vid)
    elif tool == "create_simulation":
        out = client.simulation(spec, project_id=pid, title=title, theme=theme, visual_id=vid)
    elif tool == "create_animation":
        out = client.animation(spec, project_id=pid, title=title, theme=theme, visual_id=vid)
    elif tool == "generate_3d":
        out = client.three_visual(spec.get("scene") or {}, project_id=pid, title=title,
                                  theme=theme, visual_id=vid)
    elif tool == "render_custom":
        out = client.custom(project_id=pid, code=spec.get("code", ""), html=spec.get("html", ""),
                            title=title, theme=theme, libs=spec.get("libs") or [], visual_id=vid)
    else:
        return {"status": "error", "error": f"visual {vid!r} has unknown type {tool!r}"}

    out["tool"] = tool
    if out.get("status") == "ok":
        _emit_artifacts(ctx, out, title)
    return out


def _delete_visual(ctx: ToolContext, inp: dict) -> dict:
    from ..render import visuals
    vid = str(inp.get("visual_id") or "")
    removed = visuals.delete(_project_id(ctx), vid)
    return {"status": "ok" if removed else "error",
            "removed": removed,
            **({} if removed else {"error": f"no visual with id {vid!r}"})}


def _present_visual(ctx: ToolContext, inp: dict) -> dict:
    """Surface an already-created visual again, with a note.

    For long runs: "here is what the data looks like so far, I'm continuing".
    """
    from ...security import sign_path
    from ..render import visuals

    pid = _project_id(ctx)
    vid = str(inp.get("visual_id") or "")
    rec = visuals.load_meta(pid, vid)
    if not rec:
        return {"status": "error", "error": f"no visual with id {vid!r}"}
    key = visuals.html_key(pid, vid)
    ctx.progress("artifact", {
        "name": rec.get("title") or "Visual",
        "mime": "text/html",
        "bytes": 0,
        "tool": rec.get("tool", ""),
        "visual_id": vid,
        "url": f"/api/artifact/{key}?sig={sign_path(key)}",
    })
    if inp.get("note"):
        ctx.progress("step_sub", {"text": str(inp["note"])[:200]})
    return {"status": "ok", "presented": vid}


# --- schemas ---------------------------------------------------------------

_THEME = {"type": "string", "enum": ["light", "dark"]}

DIAGRAM_SPEC = {
    "type": "object",
    "description": (
        "kind: flow | vflow | tree | timeline | concept | wireframe. "
        "flow/tree/concept take nodes:[{id,label,shape?,sub?,accent?}] and "
        "edges:[{from,to,label?}]. shape is box|round|diamond|circle|note. "
        "timeline takes items:[{when,label,detail?}]. "
        "wireframe takes blocks:[{row,col,span,row_span?,label,lines?,accent?}] "
        "on a 12-column grid. Layout is computed for you — never supply coordinates."
    ),
    "properties": {
        "kind": {"type": "string"},
        "description": {"type": "string"},
        "nodes": {"type": "array", "items": {"type": "object"}},
        "edges": {"type": "array", "items": {"type": "object"}},
        "items": {"type": "array", "items": {"type": "object"}},
        "blocks": {"type": "array", "items": {"type": "object"}},
        "caption": {"type": "string"},
    },
}

SIM_SPEC = {
    "type": "object",
    "description": (
        "mode: plot | motion | field | bar. "
        "params:[{name,label,min,max,value,unit?}] become sliders the learner drags. "
        "Formulas are STRINGS in a safe mini-language over the params plus the "
        "independent variable and (in motion mode) 't': + - * / ^ %, comparisons, "
        "ternary a?b:c, and sin cos tan asin acos atan atan2 exp log log10 sqrt abs "
        "min max pow floor ceil round sign clamp lerp step mod hypot gauss, with "
        "constants pi/e/tau. No other syntax is permitted. "
        "plot: x:{name,min,max,samples} + curves:[{label,y}]. "
        "motion: bodies:[{label,x,y,r,trail?}] + time:{max,speed}. "
        "field: field:{u,v,density} over x and y. bar: bars:[{label,value}]. "
        "view:{xmin,xmax,ymin,ymax} sets the window; readouts:[{label,expr,unit}] "
        "show live computed values. Prefer this over a static chart whenever the "
        "point is HOW something changes."
    ),
    "properties": {
        "mode": {"type": "string"},
        "description": {"type": "string"},
        "params": {"type": "array", "items": {"type": "object"}},
        "x": {"type": "object"},
        "y": {"type": "object"},
        "view": {"type": "object"},
        "curves": {"type": "array", "items": {"type": "object"}},
        "bodies": {"type": "array", "items": {"type": "object"}},
        "field": {"type": "object"},
        "bars": {"type": "array", "items": {"type": "object"}},
        "time": {"type": "object"},
        "readouts": {"type": "array", "items": {"type": "object"}},
        "caption": {"type": "string"},
    },
}

ANIM_SPEC = {
    "type": "object",
    "description": (
        "steps:[{kind,...,caption}] drawn one after another on an SVG canvas of "
        "width x height (default 720x420, origin top-left). kind is line "
        "(points:[[x,y],...]), arrow (same), rect (rect:[x,y,w,h]), circle "
        "(circle:[cx,cy,r]), or path (path: an SVG 'd' string). Each step may add "
        "text (+ text_at:[x,y]) and MUST have a caption — the caption is the "
        "narration shown while that stroke draws. Use 4-8 steps that build one "
        "idea in order."
    ),
    "properties": {
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "grid": {"type": "boolean"},
        "description": {"type": "string"},
        "step_duration": {"type": "integer"},
        "steps": {"type": "array", "items": {"type": "object"}},
        "caption": {"type": "string"},
    },
    "required": ["steps"],
}


def register_visual_tools(reg: ToolRegistry) -> None:
    reg.register(Tool(
        name="create_diagram",
        description=(
            "Draw a 2D structural diagram as crisp SVG: flowchart, tree/hierarchy, "
            "timeline, concept map, or UI wireframe. Fast, printable, and readable on "
            "a slow connection. Prefer this over 3D whenever the point is how things "
            "CONNECT rather than how they are distributed in space."
        ),
        input_schema={"type": "object", "properties": {
            "spec": DIAGRAM_SPEC, "title": {"type": "string"}, "theme": _THEME,
        }, "required": ["spec"]},
        execute=_create_diagram, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="create_simulation",
        description=(
            "Build an INTERACTIVE simulation the learner can manipulate: sliders for "
            "each parameter, live-recomputed curves, animated bodies, vector fields, or "
            "reactive bars. This is the strongest teaching tool available — reach for it "
            "whenever understanding depends on seeing how an outcome RESPONDS to a "
            "change (projectile angle, interest rate, sample size, dosage, population "
            "growth). Formulas use a restricted maths language; see the spec."
        ),
        input_schema={"type": "object", "properties": {
            "spec": SIM_SPEC, "title": {"type": "string"}, "theme": _THEME,
        }, "required": ["spec"]},
        execute=_create_simulation, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="create_animation",
        description=(
            "Produce a self-drawing animated explainer: a diagram that draws itself "
            "stroke by stroke while a caption narrates each step, whiteboard style. Use "
            "for processes and sequences where the ORDER is the lesson (a cycle, a "
            "proof, an experimental procedure, how a mechanism works)."
        ),
        input_schema={"type": "object", "properties": {
            "spec": ANIM_SPEC, "title": {"type": "string"}, "theme": _THEME,
        }, "required": ["spec"]},
        execute=_create_animation, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="create_knowledge_graph",
        description=(
            "Draw a knowledge graph / concept network as an INTERACTIVE React Flow "
            "canvas: pan, zoom, drag nodes, search to highlight, minimap, click a node "
            "for its detail. This is the right tool whenever the answer is a set of "
            "entities and the relationships between them — a literature map, a causal "
            "chain, a syllabus topic map, an argument structure, a system's parts. "
            "Prefer it over create_diagram when the reader should EXPLORE the structure "
            "rather than read a fixed picture. Every edge endpoint must be an id that "
            "exists in `nodes`, or the call is rejected. Group nodes to colour them; the "
            "legend is generated from the groups."
        ),
        input_schema={"type": "object", "properties": {
            "spec": {"type": "object", "properties": {
                "nodes": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "group": {"type": "string", "description": "Colours the node; drives the legend."},
                    "detail": {"type": "string", "description": "Shown in the side panel on click."},
                    "url": {"type": "string"},
                    "x": {"type": "number"}, "y": {"type": "number"},
                }, "required": ["id", "label"]}},
                "edges": {"type": "array", "items": {"type": "object", "properties": {
                    "source": {"type": "string"}, "target": {"type": "string"},
                    "label": {"type": "string"}, "animated": {"type": "boolean"},
                }, "required": ["source", "target"]}},
                "layout": {"type": "string", "enum": ["lr", "tb", "rl", "bt", "radial", "preset"],
                           "description": "lr/tb are layered (dagre); radial centres the "
                                          "most-connected node; preset honours x/y."},
                "caption": {"type": "string"},
            }, "required": ["nodes"]},
            "title": {"type": "string"}, "subtitle": {"type": "string"}, "theme": _THEME,
        }, "required": ["spec"]},
        execute=_create_knowledge_graph, trust_required="verified",
        requires_services=("render",),
    ))

    reg.register(Tool(
        name="create_html_page",
        description=(
            "Publish one complete, self-contained HTML page — a big responsive "
            "interactive document: a revision sheet, an explainer, a small tool, a "
            "report. Write the WHOLE document (doctype, head, styles, body, scripts) in "
            "one string. It is validated before it is stored: external URLs, CDN "
            "scripts, web fonts and network calls are rejected, so inline everything "
            "(data as literals, images as data: URIs). Write plain browser JavaScript "
            "— there is no bundler and no module resolver, so `import` statements do "
            "not work; if you use one it is rewritten to an inlined global where "
            "possible and otherwise reported back to you. If validation fails you get "
            "the specific reason: fix it and call again."
        ),
        input_schema={"type": "object", "properties": {
            "html": {"type": "string", "description": "The complete HTML document."},
            "title": {"type": "string"},
            "strict": {"type": "boolean",
                       "description": "Also fail on warnings (truncation, offline hints)."},
        }, "required": ["html"]},
        execute=_create_html_page, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="verify_artifact",
        description=(
            "OPEN a page in a real headless browser and report what actually "
            "happened: uncaught exceptions, console errors, blocked network "
            "requests, and whether anything was painted at all. This catches the "
            "failures that look perfectly fine in the source — a scene function "
            "that never returns its scene, setup code that throws halfway, a page "
            "that draws nothing — as well as the static ones (ESM syntax in a "
            "classic script, external resources, truncated files). Pass raw "
            "`html`, the `visual_id` of something you created, or a "
            "`workspace_path` to a page in the project workspace. Read-only."
        ),
        input_schema={"type": "object", "properties": {
            "html": {"type": "string"},
            "visual_id": {"type": "string"},
            "workspace_path": {"type": "string",
                               "description": "Path to an HTML file in the workspace."},
            "heavy": {"type": "boolean",
                      "description": "Allow longer to boot (3D/WebGL). Default true."},
        }},
        execute=_verify_artifact, trust_required="anonymous", requires_services=("render",),
    ))

    reg.register(Tool(
        name="render_custom",
        description=(
            "Escape hatch: write your own JavaScript to draw a visualisation none of the "
            "other tools can express. Runs in a locked-down offline sandbox — canvas, "
            "SVG, WebGL and inline data only. There is NO network: fetch, XHR, "
            "WebSocket, external images/fonts, storage and parent-page access are all "
            "blocked and the call will be rejected if the code uses them. Set "
            "libs:[\"three\"] to get THREE injected. Inline every value you need as a "
            "literal. Only use this when a spec-driven tool genuinely cannot do the job."
        ),
        input_schema={"type": "object", "properties": {
            "code": {"type": "string", "description": "JS executed on load; draw into #root."},
            "html": {"type": "string", "description": "Optional body markup."},
            "libs": {"type": "array", "items": {"type": "string", "enum": ["three"]}},
            "title": {"type": "string"}, "theme": _THEME,
        }, "required": ["code"]},
        execute=_render_custom, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="list_visuals",
        description=(
            "List every visual already generated in this project, with its visual_id, "
            "title and type. Call this before revising or deleting so you edit the right "
            "one instead of generating a near-duplicate."
        ),
        input_schema={"type": "object", "properties": {}},
        execute=_list_visuals, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="update_visual",
        description=(
            "Revise an existing visual IN PLACE by visual_id, keeping its URL so any "
            "view the user already has open updates. The spec you pass is merged over "
            "the stored one, so send only the keys that change (passing null removes a "
            "key). Use this for every follow-up edit rather than creating a new visual."
        ),
        input_schema={"type": "object", "properties": {
            "visual_id": {"type": "string"},
            "spec": {"type": "object", "description": "Partial spec merged over the stored one."},
            "title": {"type": "string"}, "theme": _THEME,
        }, "required": ["visual_id"]},
        execute=_update_visual, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="delete_visual",
        description=(
            "Permanently delete a generated visual by visual_id. Use it to clean up "
            "superseded or mistaken output so the artifact panel stays meaningful."
        ),
        input_schema={"type": "object", "properties": {
            "visual_id": {"type": "string"},
        }, "required": ["visual_id"]},
        execute=_delete_visual, trust_required="verified", requires_services=("render",),
    ))

    reg.register(Tool(
        name="present_visual",
        description=(
            "Show an existing visual to the user RIGHT NOW, mid-run, with a short note. "
            "Use this during long jobs so the user sees interim findings as they emerge "
            "instead of waiting for the whole run to finish."
        ),
        input_schema={"type": "object", "properties": {
            "visual_id": {"type": "string"},
            "note": {"type": "string", "description": "One line on what this shows so far."},
        }, "required": ["visual_id"]},
        execute=_present_visual, trust_required="verified", requires_services=("render",),
    ))
