import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appStage = path.join(frontendRoot, ".desktop-dist", "app");
const renderRoot = path.resolve(frontendRoot, "..", "render-service");
const renderStage = path.join(frontendRoot, ".desktop-dist", "render");
const npmStage = path.join(frontendRoot, ".desktop-dist", "npm");
const assetDir = path.join(frontendRoot, "desktop", "assets");
const standaloneDir = path.join(frontendRoot, ".next", "standalone");

try {
  await readFile(path.join(standaloneDir, "server.js"));
} catch {
  throw new Error("Build the Next.js standalone server before preparing desktop resources.");
}

await mkdir(path.dirname(appStage), { recursive: true });
// Copying over old stages retains files removed from the source (including
// obsolete server code and dependencies). A distribution must be a fresh copy.
for (const stage of [appStage, renderStage, npmStage]) {
  if (path.dirname(stage) !== path.join(frontendRoot, ".desktop-dist")) {
    throw new Error(`Refusing to clear unexpected desktop stage: ${stage}`);
  }
  await rm(stage, { recursive: true, force: true });
}
await cp(standaloneDir, appStage, { recursive: true, force: true });
await mkdir(path.join(appStage, ".next"), { recursive: true });
await cp(path.join(frontendRoot, ".next", "static"), path.join(appStage, ".next", "static"), { recursive: true, force: true });
await cp(path.join(frontendRoot, "public"), path.join(appStage, "public"), { recursive: true, force: true });
try {
  await readFile(path.join(renderRoot, "node_modules", "express", "package.json"));
} catch {
  const npmCli = process.env.npm_execpath;
  if (!npmCli) throw new Error("Install render-service dependencies with npm ci before preparing desktop resources.");
  const install = spawnSync(process.execPath, [npmCli, "ci", "--omit=dev"], {
    cwd: renderRoot, stdio: "inherit", windowsHide: true,
  });
  if (install.status !== 0) throw new Error("Could not install the render service dependencies.");
}
const flowBuild = spawnSync(process.execPath, [path.join(renderRoot, "build.mjs")], {
  cwd: renderRoot, stdio: "inherit", windowsHide: true,
});
if (flowBuild.status !== 0) throw new Error("Could not build the render service.");
await mkdir(renderStage, { recursive: true });
for (const entry of ["server.js", "package.json", "lib", "dist", "node_modules"]) {
  await cp(path.join(renderRoot, entry), path.join(renderStage, entry), { recursive: true, force: true });
}
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error("Run desktop preparation through npm so its CLI can be bundled.");
const npmRoot = path.dirname(path.dirname(path.resolve(npmCli)));
await readFile(path.join(npmRoot, "package.json"));
await cp(npmRoot, npmStage, { recursive: true, force: true });
await mkdir(assetDir, { recursive: true });

// The app, installer and tray icons are rasterised from public/icon.svg, the
// same file the web app uses, so every surface shows one mark. resvg is the
// render service's own rasteriser and is installed a few lines above.
const { Resvg } = createRequire(path.join(renderRoot, "package.json"))("@resvg/resvg-js");
const iconSvg = await readFile(path.join(frontendRoot, "public", "icon.svg"), "utf8");
const rasterise = (size) => new Resvg(iconSvg, { fitTo: { mode: "width", value: size } }).render().asPng();

await writeFile(path.join(assetDir, "weave.png"), rasterise(512));

// A real multi-resolution .ico: Windows picks the closest size for the
// taskbar, title bar, Start menu and tray instead of scaling one large image.
const icoSizes = [16, 24, 32, 48, 64, 128, 256];
const images = icoSizes.map(rasterise);
const header = Buffer.alloc(6);
header.writeUInt16LE(0, 0);
header.writeUInt16LE(1, 2);
header.writeUInt16LE(images.length, 4);
const entries = [];
let offset = 6 + 16 * images.length;
images.forEach((png, index) => {
  const size = icoSizes[index];
  const entry = Buffer.alloc(16);
  entry[0] = size >= 256 ? 0 : size;
  entry[1] = size >= 256 ? 0 : size;
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(png.length, 8);
  entry.writeUInt32LE(offset, 12);
  offset += png.length;
  entries.push(entry);
});
await writeFile(path.join(assetDir, "weave.ico"), Buffer.concat([header, ...entries, ...images]));

console.log("Desktop resources prepared.");
