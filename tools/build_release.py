# tools/build_release.py
"""
Baut das fertige Paket (v1.19.2): Werkzeuge holen, PyInstaller (OpenBDAuth.spec), Werkzeuge und Lizenzen
dazulegen, als ZIP verpacken (Linux: .tar.gz). Ergebnis: dist/OpenBDAuth-<Version>-<plattform>.zip – entpacken,
OpenBDAuth starten, nichts installieren. Auf GitHub baut .github/workflows/build-linux.yml das Linux-Paket.

Unter Windows entsteht zusätzlich der Installer dist/OpenBDAuth-Setup-<Version>.exe, wenn Inno Setup 6 installiert
ist (tools/OpenBDAuth.iss); mit --installer ist er Pflicht.

Aufruf:  python tools/build_release.py [--installer]
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.constants import APP_VERSION             # noqa: E402
from modules.external_tools import platform_dir    # noqa: E402
from tools.fetch_tools import install as fetch_tools   # noqa: E402


def python_licenses(dest: str):
    """Lizenztexte der Python-Pakete und von Python selbst, wie sie installiert sind."""
    import importlib.metadata as md
    packages = [("pillow", "Pillow-LICENSE.txt")]
    if sys.platform == "win32":
        packages.append(("comtypes", "comtypes-LICENSE.txt"))       # Brennen über IMAPI2 (v1.32.0)
    for dist, name in packages:
        files = [f for f in (md.distribution(dist).files or []) if "licen" in str(f).lower()]
        if files:
            shutil.copyfile(files[0].locate(), os.path.join(dest, name))
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for python_license in (os.path.join(sys.base_prefix, "LICENSE.txt"),               # Windows
                           os.path.join(sys.base_prefix, "lib", version, "LICENSE.txt")):   # Linux, macOS
        if os.path.exists(python_license):
            shutil.copyfile(python_license, os.path.join(dest, "Python-LICENSE.txt"))
            break


def linux_system_licenses(internal: str, dest: str):
    """Linux: Lizenztexte der Systembibliotheken, die PyInstaller vom Build-Rechner (Ubuntu) mitnimmt, nach
    licenses/linux-system/ – je Paket dessen /usr/share/doc/<Paket>/copyright, dazu eine Liste mit Versionen."""
    folder = os.path.join(dest, "linux-system")
    os.makedirs(folder, exist_ok=True)
    packages = {}
    for name in sorted(os.listdir(internal)):
        if ".so" not in name or os.path.islink(os.path.join(internal, name)):
            continue
        found = subprocess.run(["dpkg", "-S", f"*/{name}"], capture_output=True, text=True).stdout
        if found:
            package = found.split(":")[0].split(",")[0].strip()   # „libx11-6:amd64: /usr/lib/…“
            packages.setdefault(package, []).append(name)
    lines = ["Systembibliotheken von Ubuntu im Linux-Paket. Lizenz je Paket in <Paket>.txt, Quellcode der",
             "jeweiligen Version: https://launchpad.net/ubuntu/+source/<Quellpaket> bzw. apt source <Paket>.", ""]
    for package, libs in sorted(packages.items()):
        version = subprocess.run(["dpkg-query", "-W", "-f=${Version} (Quellpaket ${source:Package})", package],
                                 capture_output=True, text=True).stdout
        copyright_file = f"/usr/share/doc/{package}/copyright"
        if os.path.exists(copyright_file):
            shutil.copyfile(copyright_file, os.path.join(folder, f"{package}.txt"))
        lines.append(f"{package} {version}: {', '.join(libs)}")
    with open(os.path.join(folder, "README.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  {len(packages)} Systempakete, Lizenzen in {folder}")


def sign_app(bundle: str, tools: str):
    """macOS: Werkzeuge und App ad hoc neu signieren, weil das Hinzufügen der Werkzeuge die Signatur von
    PyInstaller ungültig macht. Apple Silicon startet nur signierte Programme; eine Developer-ID ist das nicht,
    der Nutzer erlaubt den ersten Start einmal selbst."""
    for name in os.listdir(tools):
        subprocess.run(["codesign", "--force", "--sign", "-", os.path.join(tools, name)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", bundle], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", bundle], check=True)


def make_dmg(folder: str, out: str):
    """macOS: Ordner als komprimiertes Disk-Image mit Verknüpfung zu „Programme“, wie bei Mac-Apps üblich: App
    hinüberziehen = installieren. hdiutil scheitert auf GitHub gelegentlich („Resource busy“)."""
    link = os.path.join(folder, "Applications")
    if not os.path.lexists(link):
        os.symlink("/Applications", link)
    for attempt in range(3):
        if subprocess.run(["hdiutil", "create", "-volname", "OpenBDAuth", "-srcfolder", folder, "-ov",
                           "-format", "UDZO", out]).returncode == 0:
            return
        print("  erneuter Versuch")
    raise SystemExit("hdiutil konnte das Disk-Image nicht erstellen.")


def make_installer(required: bool):
    """Windows: Installer mit Inno Setup (tools/OpenBDAuth.iss) aus dist/OpenBDAuth/. Ohne Inno Setup nur ein
    Hinweis, außer required (Build auf GitHub, --installer)."""
    iscc = shutil.which("iscc") or next((p for p in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
                                                     r"C:\Program Files\Inno Setup 6\ISCC.exe") if os.path.exists(p)),
                                        None)
    if iscc is None:
        if required:
            raise SystemExit("Inno Setup 6 nicht gefunden – kein Installer.")
        print("Inno Setup 6 nicht gefunden – kein Installer, nur die ZIP.")
        return
    print("Installer …")
    subprocess.run([iscc, "/Q", f"/DAppVersion={APP_VERSION}", os.path.join(ROOT, "tools", "OpenBDAuth.iss")],
                   check=True)
    setup = os.path.join(ROOT, "dist", f"OpenBDAuth-Setup-{APP_VERSION}.exe")
    print(f"Fertig: {setup} ({os.path.getsize(setup) / 1e6:.0f} MB)")


def selftest(app: str):
    """Das fertige Paket ohne Fenster prüfen (v1.25.1): Kindprozess aus der EXE, mitgeliefertes ffmpeg, je ein kurzer
    2D- und 3D-Auftrag (modules/prepare/selftest.py). Schlägt er fehl, entsteht kein ZIP."""
    import json
    import tempfile
    exe = os.path.join(app, "OpenBDAuth.exe" if os.name == "nt" else "OpenBDAuth")
    report_path = os.path.join(tempfile.gettempdir(), "openbdauth_build_selbsttest.json")
    if os.path.exists(report_path):
        os.remove(report_path)
    print("Selbsttest des Pakets …")
    code = subprocess.run([exe, "--selbsttest", report_path], timeout=600).returncode
    report = {}
    if os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    print(json.dumps(report, indent=1, ensure_ascii=False))
    if code != 0 or not report.get("ok"):
        raise SystemExit("Selbsttest fehlgeschlagen – kein ZIP gebaut.")


def main():
    platform = platform_dir()
    tools = fetch_tools(platform)

    print("PyInstaller …")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    os.path.join(ROOT, "OpenBDAuth.spec")], cwd=ROOT, check=True)
    app = os.path.join(ROOT, "dist", "OpenBDAuth")
    exe_dir = app
    if platform == "macos":
        # Das Paket ist ein Ordner mit OpenBDAuth.app und den Lizenzen; den Ordner ohne App aus COLLECT
        # braucht es nicht mehr
        shutil.rmtree(app)
        os.makedirs(app)
        shutil.move(os.path.join(ROOT, "dist", "OpenBDAuth.app"), app)
        exe_dir = os.path.join(app, "OpenBDAuth.app", "Contents", "MacOS")
    licenses = os.path.join(app, "licenses")
    os.makedirs(licenses, exist_ok=True)

    # Werkzeuge neben die EXE: dort sucht modules/external_tools.py zuerst. In der .app dürfen unter
    # Contents/MacOS nur Programme liegen, ihre Lizenzen kommen deshalb zu den übrigen neben die App.
    tool_dest = os.path.join(exe_dir, "tools", platform)
    if platform == "macos":
        shutil.copytree(tools, tool_dest, ignore=shutil.ignore_patterns("licenses"), dirs_exist_ok=True)
        for name in os.listdir(os.path.join(tools, "licenses")):
            shutil.copyfile(os.path.join(tools, "licenses", name), os.path.join(licenses, name))
        sign_app(os.path.join(app, "OpenBDAuth.app"), tool_dest)
    else:
        shutil.copytree(tools, tool_dest, dirs_exist_ok=True)

    for name in os.listdir(os.path.join(ROOT, "licenses")):
        shutil.copyfile(os.path.join(ROOT, "licenses", name), os.path.join(licenses, name))
    for name in ("LiberationSans", "NotoSans"):
        shutil.copyfile(os.path.join(ROOT, "assets", "fonts", f"LICENSE-{name}.txt"),
                        os.path.join(licenses, f"{name}-LICENSE.txt"))
    python_licenses(licenses)
    if platform == "linux":
        linux_system_licenses(os.path.join(app, "_internal"), licenses)
    for name in ("THIRD_PARTY_LICENSES.md", "LICENSE"):
        if os.path.exists(os.path.join(ROOT, name)):
            shutil.copyfile(os.path.join(ROOT, name), os.path.join(app, name))

    selftest(exe_dir)

    # Linux: .tar.gz, das die Ausführrechte von OpenBDAuth, ffmpeg und tsMuxeR sicher mitnimmt.
    # macOS: .dmg, das die Verknüpfungen in der App und ihre Signatur unverändert lässt.
    archive = os.path.join(ROOT, "dist", f"OpenBDAuth-{APP_VERSION}-{platform}")
    print("Archiv …")
    if platform == "macos":
        ext = ".dmg"
        make_dmg(app, archive + ext)
    else:
        kind, ext = ("gztar", ".tar.gz") if platform == "linux" else ("zip", ".zip")
        shutil.make_archive(archive, kind, os.path.join(ROOT, "dist"), "OpenBDAuth")
    print(f"Fertig: {archive}{ext} ({os.path.getsize(archive + ext) / 1e6:.0f} MB)")
    if platform == "windows":
        make_installer(required="--installer" in sys.argv)


if __name__ == "__main__":
    main()
