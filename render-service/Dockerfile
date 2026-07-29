FROM node:22-slim
WORKDIR /app
COPY package.json ./
# --ignore-scripts: babylonjs ships a postinstall that only prints a support
# banner, and it hard-crashes on some hosts. We consume the prebuilt UMD bundles
# (node_modules/babylonjs/babylon.js etc.) directly, so no package here needs a
# build step — skipping them is both safer and considerably faster.
RUN npm install --omit=dev --ignore-scripts --no-audit --no-fund
COPY . .
# Fail the BUILD, not the first request, if a bundle we inline is missing.
# A render service that starts and then reports "babylon unavailable" for every
# scene is much harder to diagnose than an image that refuses to build.
RUN node -e "const {existsSync}=require('fs');\
const need=['node_modules/babylonjs/babylon.js','node_modules/three/build/three.min.js'];\
const missing=need.filter(p=>!existsSync(p));\
if(missing.length){console.error('missing render bundles:',missing.join(', '));process.exit(1);}\
console.log('render bundles present');"
EXPOSE 3100
CMD ["npm", "start"]
