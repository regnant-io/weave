FROM node:22-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
WORKDIR /app
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
# --ignore-scripts: babylonjs ships a postinstall that only prints a support
# banner, and it hard-crashes on some hosts. We consume the prebuilt UMD bundles
# (node_modules/babylonjs/babylon.js etc.) directly, so no package here needs a
# build step — skipping them is both safer and considerably faster.
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund

COPY . .

# React Flow publishes ESM/CJS only. Bundle it to a single IIFE here so generated
# graph artifacts stay self-contained (no CDN, CSP-safe) at request time.
RUN npm run build:flow

# Fail the BUILD, not the first request, if a bundle we inline is missing.
# A render service that starts and then reports "babylon unavailable" for every
# scene is much harder to diagnose than an image that refuses to build — which is
# exactly how a stale image went unnoticed for a fortnight once already.
RUN node -e "const {existsSync}=require('fs');\
const need=['node_modules/babylonjs/babylon.js',\
'node_modules/babylonjs-loaders/babylonjs.loaders.min.js',\
'node_modules/babylonjs-gui/babylon.gui.min.js',\
'node_modules/three/build/three.min.js',\
'node_modules/reactflow/dist/style.css',\
'dist/weaveflow.js'];\
const missing=need.filter(p=>!existsSync(p));\
if(missing.length){console.error('missing render bundles:',missing.join(', '));process.exit(1);}\
console.log('render bundles present');"

# npm is a build tool here. Keeping its package manager, archive, and signature
# clients in the runtime image adds a large unused attack surface.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
    /usr/local/bin/yarn /usr/local/bin/yarnpkg /usr/local/bin/pnpm /usr/local/bin/pnpx

USER node

EXPOSE 3100
CMD ["node", "server.js"]
