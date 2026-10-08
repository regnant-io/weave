# Tool runtime audit (2026-09-26)

This inventory covers all 52 tools registered by
`backend/app/services/tools/builtin.py` and its registration modules. Gotenberg
is excluded. `submit_plan`, `update_plan` and `submit_review` are orchestration
controls, separate from the service tool registry.

Availability is conditional: the registry checks mode, trust, intent and required
services both when advertising and executing a tool. The orchestrator wires only
enabled render, workspace, warehouse and web services; canvas requires a database
session and `ask_user` requires a live response client. A capability hidden by a
deployment setting is not a successful execution. An enabled service also does
not guarantee its upstream is currently reachable.

## Complete inventory and runtime contract

| Tools | Windows desktop | Docker / development | Evidence and limits |
| --- | --- | --- | --- |
| `check_citation` (1) | Python stdlib reference checks | Same backend code | `test_api.py::test_citation_check_flags_predatory`; registry tests. This is a heuristic citation flag, not external bibliographic verification. |
| `search_library` (1) | Local database and retrieval service | Configured database; deployed retrieval can use Postgres/pgvector | `test_retrieval.py` exercises ingestion, hybrid search, language expansion and predatory flags. Current host suite uses its test database, not a fresh deployed Postgres instance. |
| `run_analysis`, `query_warehouse` (2) | Frozen Python scientific stack; DuckDB; a ready attached dataset | Pinned Python requirements; subprocess analysis for dev, configured isolated executor for production | `test_sandbox.py`, `test_dataset_pipeline.py`, `test_warehouse.py` cover real execution, plots, CSV/JSON/XLSX/Parquet readers, SQL and failure reporting. `weave-backend.spec` includes SciPy/statsmodels/seaborn/PyArrow/OpenPyXL/XLRD and Python check modules. Production overlay deliberately disables local analysis execution. |
| `web_search`, `fetch_url`, `deep_research` (3) | Keyless public search; HTTP fetch; bundled browser service for supported browser work | SearXNG URL; optional Browserless URL and `deep` services | `test_hardening.py` covers keyless parsing, provider failover, outages and dates; `test_tools.py` covers SSRF, redirects and byte limits. Internet providers can throttle or change: parser and failure tests do not establish live provider availability. |
| `generate_visual`, `generate_deck`, `create_3d_experience`, `generate_3d`, `create_diagram`, `create_simulation`, `create_animation`, `create_knowledge_graph`, `create_html_page`, `render_custom` (10) | Bundled Node render service, browser worker and renderer dependencies | Node render service and built browser bundles via `deep` profile | Render `server.test.js` and `hardening.test.js` cover renderer endpoints and rejection contracts. Backend tests cover rejected specs and static/runtime verification distinction. Babylon asset references additionally require existing workspace files. HTML decks work without Gotenberg. PDF conversion remains unavailable on desktop because the optional Gotenberg service is excluded. |
| `verify_artifact`, `list_visuals`, `update_visual`, `delete_visual`, `present_visual` (5) | Render client, visual registry/storage; browser for runtime verification | Same clients with configured render/browser services | Render and backend contract suites cover relevant service boundaries. Registry CRUD tool adapters have been inspected; a contract suite is not a claim that every adapter completed a live user flow on every OS. Runtime-unavailable verification must remain distinct from a verified artifact. |
| `ask_user` (1) | Live chat interaction and cancellation | Live chat interaction; hidden for batch turns | `test_regressions.py` exercises interruptible waits and user-scoped answers. |
| `remember`, `recall`, `forget` (3) | Database-backed project/user memory | Same memory service and configured database | `test_tool_adapters.py` executes all three registry adapters with real SQLite memory rows and asserts recall/removal; shared backend suite covers project/thread isolation. |
| `canvas_read`, `canvas_edit`, `canvas_append`, `canvas_write`, `canvas_create`, `canvas_list` (6) | Database session and shared canvas service | Same service/database contract | `test_tool_adapters.py` executes all six registry adapters with a real canvas/database and asserts actual contents plus stale-anchor rejection. `test_api.py::test_project_with_default_canvas_can_be_deleted` covers lifecycle. |
| `list_skills`, `read_skill` (2) | Bundled Markdown skill library | Library copied with backend source | `weave-backend.spec` explicitly bundles `app/services/skills/library`; `test_tool_adapters.py` lists the actual Markdown library and reads a nonempty procedure through the registry. |
| `delegate` (1) | A configured model and at least one read capability | Same scoped orchestration worker | `test_subagent.py` covers read-only schemas, execution allowlist, sources, absent tools, output limits and empty tasks. A real remote model remains dependent on provider credentials/availability. |
| `workspace_write`, `workspace_edit`, `workspace_read`, `workspace_list`, `workspace_delete`, `workspace_move`, `workspace_grep`, `workspace_glob`, `workspace_package` (9) | Native project directories; Python file/archive operations | Docker-backed workspace service enabled with the workspace image; project volume | `test_regressions.py` covers path containment, edit ambiguity and truncated source detection. Workspace paths and archive handling inspected. Native smokes are separate from Docker volume/container smokes. |
| `workspace_exec`, `workspace_check`, `workspace_verify` (3) | Bundled node/npm/npx and frozen Python CLI; PowerShell on Windows, preserved shim PATH on POSIX | Workspace image supplies bash, Node, npm, Python, pytest, build tools and optional media tools | `test_distribution_runtime.py` covers Python flags/modules/exit propagation and POSIX PATH; `test_hardening.py` covers PowerShell chaining, manifest check discovery, watch-mode rejection, first failure and missing checks. Additional generated-project dependencies still require installation. Git, FFmpeg and ImageMagick are not bundled desktop promises. |
| `workspace_serve`, `preview_check`, `workspace_stop_server`, `workspace_server_log` (4) | Native child server plus bundled browser worker | Workspace container, forwarded dev ports and configured browser service | `test_distribution_runtime.py` covers occupied-port rejection; desktop/browser contract tests cover local runtime boundaries. A reachable port alone does not establish a working application: `preview_check` supplies runtime evidence. |
| `workspace_git` (1) | System Git if installed | Git installed by `workspace-image/Dockerfile` | `test_distribution_runtime.py` covers ignored files, bad refs and option-shaped refs when Git is present. Git is optional on desktop and cannot be claimed bundled. Missing executable failures remain actionable. |

Counts sum to 52. Anonymous accounts cannot use verified-only capabilities;
desktop accounts are promoted to verified by the desktop-only account policy.
Production's overlay intentionally sets `WEAVE_WORKSPACE_ENABLED=false` and
`WEAVE_ANALYSIS_EXECUTION_ENABLED=false`; it does not promise unrestricted local
execution. Docker dev's override installs Docker CLI, mounts the socket and
enables workspaces. The base image does not grant this host access.

## Current validation boundary

The task's final local run reported 278 backend tests passed, 18 render tests
passed, 4 desktop lifecycle tests passed and 8 browser journeys passed. Those are
regression/contract results, not 52 times three live tool executions. Native
packaged runtime smokes and installer artifacts are reported separately in the
task result.

The final Windows 1.0.2 package passed unpatched checks from an isolated directory:
all 52 registrations, standalone frontend startup, frozen Python/pytest, dataset
formats and plots, real SQL, bundled Node/npm/npx, workspace checks/Git/archives,
and chart/deck/custom HTML/3D inspection in Chromium. All 99 bundled application
modules matched final source and the removed repair module was absent. The actual
desktop app was then launched with healthy frontend/backend/render/browser services.

A subsequent focused adapter run passed 33 tests across `test_tool_adapters.py`,
`test_tools.py`, `test_regressions.py` and `test_distribution_runtime.py`. Its
three new tests execute 24 local adapters against real SQLite, Markdown library,
workspace files/archives and visual object storage. They also caught and verified
fixes for source JSON sidecars appearing as phantom visuals and unavailable PDF
exports reporting HTML-only output as success. PDF is now excluded from the deck
schema when no converter is configured; direct PDF requests fail before rendering.
Visual update/render and remote providers are outside this particular local smoke.

This Windows host has no usable Docker executable/runtime for a fresh container
integration run. Docker build/volume/network contracts are inspected from the
Dockerfiles and Compose manifests and exercised where covered by unit tests;
fresh image builds and live Docker tool execution remain unverified in this run.
macOS and Linux distributions likewise require native packaging and execution
on their target systems. No current fresh Docker, macOS or Linux success is
inferred from older audit notes.

No concrete missing scientific module was found in the current manifest review:
the advertised PyArrow, seaborn, XLSX/XLS readers and frozen Python check modules
are explicitly included. Packaged execution, external search, remote model and
target-OS checks determine actual availability; missing inputs/services must
produce unavailable/error results rather than success claims.
