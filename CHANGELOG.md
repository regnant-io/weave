# Changelog

## 1.0.2 — 2026-09-26

- Replaced the post-generation artifact repair gate with task orchestration that
  executes, inspects, validates, audits, fixes and rechecks substantial work.
  Plans now retain unfinished commitments, dependencies and acceptance checks;
  completed steps cite tool evidence. Single deliverables no longer complete
  unrelated plan steps, and unresolved gaps cannot silently become success.
  Replans and resumes preserve the full accumulated ledger and remap dependencies.
- Persisted task checkpoints during execution. Same-thread `continue`/`resume`
  restores useful work with matching project and dataset context. Budget,
  cancellation, unavailable validation and repeated failed attempts remain visible.
  Simple chat and small actions avoid heavyweight planning and review.
- Unified CSV/JSON/Excel/Parquet parsing across profiling, Python analysis and
  SQL. Added encoding, malformed-row, nested-value and null handling; bounded CSV
  statistics disclose sampling. Failed datasets cannot execute or appear analysed.
  Analysis and SQL results include source IDs and truncation metadata.
- Fixed desktop Python verification and imports, bundled the advertised analysis
  dependencies and pytest, preserved tool PATH on POSIX, and provided the Docker
  `python` alias. Docker availability recovers after daemon reconnects.
  Frozen Windows analysis preserves required system settings, stores temporary
  configuration outside the installation and reports child startup failures.
  Bundled npm/node launchers now quote preload paths correctly, including spaces.
- Hardened desktop navigation, tray/shutdown behavior, subprocess cleanup,
  preview-port collision handling, Git error reporting and log rotation.
- Removed phantom visual entries created by source sidecars. Unsupported PDF
  exports are hidden and fail explicitly; HTML decks remain available without
  Gotenberg.
- Desktop packaging starts from fresh staging and rejects cross-OS frozen builds.
  Gotenberg is excluded from desktop services. Generated distributions are ignored
  by Git, TypeScript and ESLint. Windows desktop release version is now 1.0.2.

Validation: 278 backend tests, 18 render-service tests, 4 desktop lifecycle tests
and 8 browser journeys passed (3 mobile duplicate journeys skipped).
Frontend typecheck/lint/build, production npm audits and the pinned Python
dependency audit passed with no known vulnerabilities reported. The final Windows
package passed isolated, unpatched runtime checks for all 52 tool registrations,
the Next.js homepage, frozen Python/pytest, dataset formats, plotting, SQL,
Node/npm/npx, workspace checks/Git/archives and Chromium/WebGL rendering.
All 99 bundled backend modules match the final source; the removed repair module
is absent. Unsupported PDF correctly fails without Gotenberg.
Windows installer `Weave-Setup-1.0.2-x64.exe` built successfully. The packaged
desktop app was launched and its window, frontend, backend, render and browser
services were verified healthy. Old builds, staging and test debris were archived
outside the repository; the final installer and running distribution are retained.
Docker runtime checks and macOS/Linux installer execution require those hosts;
live provider-dependent behavior remains dependent on configured services.
