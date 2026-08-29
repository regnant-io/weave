---
name: interactive-3d-scene
title: Building an interactive Babylon.js scene
description: How to write a Babylon scene that actually runs offline in the artifact sandbox — engine setup, controls, assets, performance, and what to do when it comes back broken.
tags: babylon, 3d, game, simulation, walkthrough, webgl
---

Use `create_3d_experience` when the reader should MOVE THROUGH or PLAY WITH
something: a building walkthrough, a physics toy, a molecular model they rotate,
a small game, a 3D builder. Use `generate_3d` instead for a 3D *chart* (a
response surface, a three-variable scatter) — that is spec-driven and you should
not hand-write it.

## What you write, and what you do not

You write the **body of `createScene(engine, canvas, BABYLON, assets)`**, and you
`return` a `BABYLON.Scene`. That is all.

Engine construction, the resize handler, the render loop, the loading state,
pointer-lock hygiene, the FPS readout and error surfacing are already provided.
Do not recreate them — regenerating that boilerplate is where scenes usually
break.

```js
const scene = new BABYLON.Scene(engine);
const camera = new BABYLON.ArcRotateCamera("cam", -Math.PI/2, Math.PI/3, 12,
                                           BABYLON.Vector3.Zero(), scene);
camera.attachControl(canvas, true);
new BABYLON.HemisphericLight("light", new BABYLON.Vector3(0, 1, 0), scene);
// … your content …
return scene;
```

The `canvas` argument is the canvas. You do not need `getElementById`, and
reaching for it is how tutorial habits leak in. (If you do, the canvas is
`renderCanvas`, and the common alternatives are aliased, so it will still work —
but the argument is right there.)

**Your function may be `async`.** Awaiting `BABYLON.SceneLoader.ImportMeshAsync`
and returning the scene afterwards is correct and supported. Returning a Promise
that resolves to a scene is also fine.

## Hard constraints

- **No network.** No `fetch`, no URL textures, no CDN. Meshes, textures and
  audio travel inline through the `assets` argument as data URLs.
- **No `import`.** `BABYLON` is a global.
- Set `libs: ["loaders"]` if you import a `.glb`/`.obj`, `libs: ["gui"]` if you
  use `BABYLON.GUI`. They are heavy; do not request them otherwise.

## Camera choice

- `ArcRotateCamera` — the default. Orbit an object. Right for models, molecules,
  data.
- `UniversalCamera` — first person. Right for walkthroughs. Set
  `camera.checkCollisions`, `scene.collisionsEnabled` and an `ellipsoid` or the
  user walks through walls.
- `FollowCamera` — chase a moving body in a game.

Always `camera.attachControl(canvas, true)`, and pass a `controls` string
("Drag to orbit · Scroll to zoom") so the hint line tells the user what to do.

A scene with **no camera at all** draws nothing and throws nothing — the most
confusing failure available. One is added automatically if you forget, but an
automatic camera almost never frames the subject well, so place your own.

## Make it teach

A scene the reader only looks at is a still image that cost more. Give it one
thing to change and one thing to observe: a slider that alters gravity, a
toggle that reveals a cross-section, a click that labels a part. Use
`scene.onPointerObservable` for picking, and `BABYLON.GUI` for on-canvas
controls when you need them.

## Performance — assume a mid-range Android phone

- Use `MeshBuilder` primitives and instancing (`createInstance`) over many
  distinct meshes.
- Freeze what never moves: `mesh.freezeWorldMatrix()`, `scene.freezeActiveMeshes()`.
- Keep total inlined assets well under the 24MB cap; a scene that will not load
  is worse than a simpler one that does.
- Reuse materials. One material shared across 200 instances, not 200 materials.

## When it comes back broken

Every scene is opened in a real browser before the user sees it, so a failure
comes back to you as a failed tool call with the specific error. Three of them
have a specific cause worth knowing:

| What you are told | What it actually means |
|---|---|
| "does not parse … around line N" | An unclosed bracket, brace or string. The rest of the file is fine — go to that line. |
| "finished without returning a BABYLON.Scene" | You built the scene and never returned it. Add `return scene;`. |
| "no active camera" | You created a camera but never attached it to this scene, or created none. |

**Fix it by editing, not by writing it again.** Call `update_visual` with the
`visual_id` and the corrected `code`, changing the smallest thing that fixes the
fault. Regenerating four hundred lines to fix one missing `return` produces four
hundred *different* lines, with a new fault in them about as often as not — and
you only get two repair attempts. Everything that already worked is currently
correct; keep it.

## Finish

Say in prose what the scene shows, what the user should try, and what they
should notice when they do. A scene handed over without that is a toy; with it,
it is a demonstration.
