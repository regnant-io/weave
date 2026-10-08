# Build with: python -m PyInstaller --noconfirm --clean weave-backend.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from pathlib import Path

root = Path.cwd()
datas = [
    (str(root / "app" / "services" / "skills" / "library"), "app/services/skills/library"),
    (str(root / "app" / "seed" / "sources.json"), "app/seed"),
    (str(root / "migrations"), "migrations"),
]
datas += collect_data_files("statsmodels", excludes=["**/tests/**", "**/test/**"])
binaries = []
hiddenimports = collect_submodules("app")
hiddenimports += ["compileall", "py_compile"]

# Model generated analysis may import any public SciPy or statsmodels module.
# Include those production modules while excluding their test suites. The
# standard PyInstaller hooks collect native libraries for NumPy, pandas,
# SciPy, matplotlib and the app's other direct dependencies.
def production_module(name):
    return not any(part in {"test", "tests", "testing", "conftest"}
                   for part in name.split("."))


for package in ("scipy", "statsmodels", "seaborn", "pyarrow", "openpyxl", "xlrd", "pytest", "_pytest"):
    hiddenimports += collect_submodules(package, filter=production_module)

a = Analysis(
    [str(root / "app" / "desktop_entry.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "torch", "tensorflow", "onnxruntime"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="weave-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="weave-backend",
)
