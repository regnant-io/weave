FROM node:22-slim
WORKDIR /app
COPY package.json ./
# --ignore-scripts: babylonjs ships a postinstall that only prints a support
# banner, and it hard-crashes on some hosts. We consume the prebuilt UMD bundles
# (node_modules/babylonjs/babylon.js etc.) directly, so no package here needs a
# build step — skipping them is both safer and considerably faster.
RUN npm install --omit=dev --ignore-scripts --no-audit --no-fund

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

EXPOSE 3100
CMD ["npm", "start"]
