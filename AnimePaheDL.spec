# PyInstaller spec - build with:  pyinstaller AnimePaheDL.spec --noconfirm
# Produces dist/AnimePaheDL/AnimePaheDL.exe (one-folder build: starts fast, WebEngine friendly).
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for package in ("curl_cffi",):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore"],
    excludes=[
        "tkinter", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtSql",
        "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    ],
    noarchive=False,
)

# The GUI is QtWidgets-only: drop QML/Quick plugins and non-English Qt translations to save space.
def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    if "/qml/" in dest:
        return False
    if "/translations/" in dest and not any(t in dest for t in ("_en", "qtwebengine_locales/en")):
        return False
    return True


a.datas = [e for e in a.datas if _keep(e)]
a.binaries = [e for e in a.binaries if _keep(e)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AnimePaheDL",
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AnimePaheDL")
