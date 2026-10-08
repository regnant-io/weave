import { access } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(frontendRoot, "..");
const backendRoot = path.join(repoRoot, "backend");
const target = process.argv[2];
const python = process.env.WEAVE_PYTHON || "python";

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit", windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with status ${result.status}`);
}

if (!["windows", "mac", "linux"].includes(target)) {
  throw new Error("Choose one target: windows, mac, or linux.");
}
const hostTarget = { win32: "windows", darwin: "mac", linux: "linux" }[process.platform];
if (target !== hostTarget) {
  throw new Error(`The ${target} distribution must be built on ${target}; the frozen backend is native to the build host (${hostTarget || process.platform}).`);
}

const pyinstaller = spawnSync(python, ["-m", "PyInstaller", "--version"], {
  cwd: backendRoot,
  encoding: "utf8",
  windowsHide: true,
});
if (pyinstaller.status !== 0) {
  throw new Error(`PyInstaller is not installed for ${python}. Install the backend requirements and PyInstaller first.`);
}

const runtimeImports = [
  "alembic", "anthropic", "boto3", "celery", "duckdb", "fastapi", "httpx",
  "matplotlib", "multipart", "numpy", "openpyxl", "opentelemetry", "pandas",
  "pgvector", "psycopg", "pydantic_settings", "pypdf", "redis", "scipy",
  "sqlalchemy", "statsmodels", "trafilatura", "uvicorn", "seaborn", "pyarrow",
  "xlrd", "pytest",
];
const dependencyCheck = spawnSync(python, [
  "-c",
  "import importlib.util,sys; names=" + JSON.stringify(runtimeImports) + "; missing=[n for n in names if importlib.util.find_spec(n) is None]; print('\\n'.join(missing)); sys.exit(bool(missing))",
], { cwd: backendRoot, encoding: "utf8", windowsHide: true });
if (dependencyCheck.status !== 0) {
  const missing = dependencyCheck.stdout.trim().split(/\r?\n/).filter(Boolean).join(", ");
  throw new Error(`Install the missing backend runtime packages before packaging: ${missing}`);
}

run(python, [
  "-m", "PyInstaller", "--noconfirm", "--clean",
  "--distpath", path.join(backendRoot, "dist"),
  "--workpath", path.join(backendRoot, "build"),
  "weave-backend.spec",
], backendRoot);
await access(path.join(backendRoot, "dist", "weave-backend"));

const cli = path.join(frontendRoot, "node_modules", "electron-builder", "cli.js");
await access(cli);
const args = target === "windows"
  ? ["--win", "nsis"]
  : target === "mac"
    ? ["--mac", "dmg"]
    : ["--linux", "AppImage", "deb"];
// WEAVE_DESKTOP_OUT builds into another folder, so a copy of Weave that is
// running from dist/win-unpacked does not lock the build out of its files.
const output = process.env.WEAVE_DESKTOP_OUT;
if (output) args.push(`-c.directories.output=${output}`);
run(process.execPath, [cli, ...args], frontendRoot);
