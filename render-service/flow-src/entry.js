// Bundle entry for the React Flow runtime that ships inside generated graph
// artifacts.
//
// Weave's house rule is that every artifact is fully self-contained: no CDN, no
// network at runtime, CSP-safe. React Flow only publishes ESM/CJS, so there is
// no UMD build we could inline the way we inline Babylon and Three. esbuild
// turns it into a single IIFE at image-build time and `server.js` reads the
// result off disk once at boot.
//
// Everything the generated page needs is hung off one global. The page itself is
// written by this service (see lib/graph.js) — the model only ever supplies the
// graph as DATA, never as code.
import React from "react";
import { createRoot } from "react-dom/client";
import * as ReactFlow from "reactflow";
import dagre from "dagre";

window.WeaveFlow = { React, createRoot, ReactFlow, dagre };
