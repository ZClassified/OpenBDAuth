# -*- mode: python ; coding: utf-8 -*-
# OpenBDAuth als Ordner-Paket (v1.19.2): eine EXE plus Ordner _internal mit Python, Qt und den Programmdateien.
# Ordner statt Ein-Datei-EXE: Die Qt-Bibliotheken liegen als einzelne Dateien vor und lassen sich austauschen (LGPL),
# und das Programm startet schneller. Werkzeuge und Lizenzen ergänzt tools/build_release.py neben der EXE.

excludes = [
    'torch', 'torchvision', 'torchaudio', 'scipy', 'pandas', 'matplotlib',
    'cv2', 'sklearn', 'streamlit', 'transformers', 'diffusers', 'accelerate',
    'fastapi', 'uvicorn', 'watchdog', 'websockets', 'pyarrow', 'numba', 'onnx',
    'tkinter', 'customtkinter', 'flet', 'IPython', 'notebook', 'nbformat',
    'tests', 'numpy', 'yaml', 'pygame', 'requests', 'charset_normalizer',
    # OpenBDAuth nutzt nur QtCore, QtGui und QtWidgets
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtNetwork', 'PySide6.QtPdf', 'PySide6.QtOpenGL',
    'PySide6.QtSvg', 'PySide6.QtDBus', 'PySide6.QtMultimedia',
]

# Qt-Dateien, die OpenBDAuth nicht braucht: Übersetzungen der Qt-Dialoge (~100 MB, OpenBDAuth hat eigene Texte),
# Software-OpenGL, Quick/QML/PDF/Netzwerk samt ihrer Plugins
DROP = ('PySide6/translations', 'opengl32sw', 'Qt6Quick', 'Qt6Qml', 'Qt6Pdf', 'Qt6Network', 'Qt6OpenGL',
        'Qt6VirtualKeyboard', 'qpdf', 'qtvirtualkeyboard', 'qmltooling', 'Qt6Svg', 'qsvg')

# Linux: das GTK-Design-Plugin von Qt samt GTK, Pango und Cairo von Ubuntu (OpenBDAuth hat ein eigenes Design), dazu
# libstdc++ und libgcc_s – die bringt jedes Linux in neuerer Version mit, die alte von Ubuntu 22.04 im Paket
# verträgt sich auf neueren Systemen nicht mit den Grafiktreibern
import sys
if sys.platform.startswith('linux'):
    DROP += ('libqgtk3', 'libgtk-3', 'libgdk-3', 'libgdk_pixbuf', 'libatk-', 'libatspi', 'libpango', 'libcairo',
             'libepoxy', 'libpixman', 'libthai', 'libdatrie', 'libgraphite2', 'libharfbuzz.so', 'libstdc++',
             'libgcc_s')


def keep(entries):
    return [e for e in entries if not any(d.lower() in e[0].replace(chr(92), '/').lower() for d in DROP)]

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('assets', 'assets')],
    # comtypes (nur Windows, Brennen über IMAPI2): spätes Binden, es wird kein comtypes.gen erzeugt
    hiddenimports=['shiboken6'] + (['comtypes.client.dynamic', 'comtypes.connectionpoints']
                                   if sys.platform == 'win32' else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

a.binaries = keep(a.binaries)
a.datas = keep(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OpenBDAuth',
    icon='assets/icon/openbdauth.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='OpenBDAuth',
)

# macOS: zusätzlich OpenBDAuth.app, damit das Programm per Doppelklick im Finder startet (tools/build_release.py
# legt die Werkzeuge hinein und signiert neu)
if sys.platform == 'darwin':
    sys.path.insert(0, SPECPATH)
    from core.constants import APP_VERSION
    app = BUNDLE(
        coll,
        name='OpenBDAuth.app',
        icon='assets/icon/openbdauth_1024.png',
        bundle_identifier='io.github.zclassified.openbdauth',
        info_plist={
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '13.0',
        },
    )
