# -*- coding: utf-8 -*-
"""
Launcher moda „Oświecenie" (1700 A.D.) dla 0 A.D. Release 28.

Co robi:
  1. Odczytuje wersję zainstalowanego moda z mods/oswiecenie/mod.json.
  2. Sprawdza najnowsze wydanie (Release) w repozytorium GitHub.
  3. Pobiera paczkę .zip, sprawdza ją i bezpiecznie podmienia folder moda.
  4. Uruchamia 0 A.D. z włączonym modem.

Wymaga wyłącznie biblioteki standardowej Pythona (tkinter, urllib, zipfile).
"""

import ctypes
import glob
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Konfiguracja — można ją nadpisać plikiem launcher.json obok pliku .exe
# ---------------------------------------------------------------------------
LAUNCHER_VERSION = "1.0.0"
DEFAULT_CONFIG = {
    "github_repo": "kubusk2012-cpu/oswiecenie_launcher.py",  # repozytorium musi być publiczne
    "mod_name": "oswiecenie",          # nazwa folderu moda i pole "name" w mod.json
    "asset_prefix": "oswiecenie",      # paczka w wydaniu: oswiecenie-<wersja>.zip
    "game_args": ["-mod=public", "-mod=oswiecenie"],
}
API_BASE = os.environ.get("OSWIECENIE_API_BASE", "https://api.github.com")
USER_AGENT = "OswiecenieLauncher/" + LAUNCHER_VERSION
CHUNK = 256 * 1024


def app_dir() -> Path:
    """Folder, w którym leży launcher (.exe lub .py)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    path = app_dir() / "launcher.json"
    if path.is_file():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return cfg


# ---------------------------------------------------------------------------
# Ścieżki
# ---------------------------------------------------------------------------
def documents_dir() -> Path:
    """Prawdziwy folder Dokumenty (także przekierowany do OneDrive)."""
    if os.name == "nt":
        try:
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
            fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                       (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
            out = ctypes.c_wchar_p()
            fn = ctypes.windll.shell32.SHGetKnownFolderPath
            fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                           ctypes.POINTER(ctypes.c_wchar_p)]
            if fn(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
                result = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                return result
        except Exception:
            pass
    return Path.home() / "Documents"


def default_mods_dir() -> Path:
    if os.name == "nt":
        return documents_dir() / "My Games" / "0ad" / "mods"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "0ad" / "mods"
    xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(xdg) / "0ad" / "mods"


def settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".config")
    return Path(base) / "OswiecenieLauncher" / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def find_game_exe(settings: dict):
    """Szuka pyrogenesis.exe: zapisana ścieżka → rejestr → typowe foldery."""
    saved = settings.get("game_exe")
    if saved and Path(saved).is_file():
        return Path(saved)
    if os.name != "nt":
        found = shutil.which("0ad") or shutil.which("pyrogenesis")
        return Path(found) if found else None

    candidates = []
    try:
        import winreg
        roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        for hive, key in roots:
            try:
                with winreg.OpenKey(hive, key) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                                name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                                if "0 A.D" not in name:
                                    continue
                                for field in ("InstallLocation", "UninstallString"):
                                    try:
                                        val = str(winreg.QueryValueEx(sub, field)[0]).strip('"')
                                    except OSError:
                                        continue
                                    base = Path(val) if field == "InstallLocation" else Path(val).parent
                                    candidates.append(base / "binaries" / "system" / "pyrogenesis.exe")
                        except OSError:
                            continue
            except OSError:
                continue
    except ImportError:
        pass

    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if not root:
            continue
        for sub in ("", "Programs"):
            pattern = os.path.join(root, sub, "0 A.D*", "binaries", "system", "pyrogenesis.exe")
            candidates += [Path(p) for p in glob.glob(pattern)]

    for c in candidates:
        if c.is_file():
            return c
    return None


# ---------------------------------------------------------------------------
# Wersje i wydania
# ---------------------------------------------------------------------------
def read_local_version(mod_dir: Path):
    try:
        data = json.loads((mod_dir / "mod.json").read_text(encoding="utf-8-sig"))
        return str(data.get("version", "")) or None
    except (OSError, ValueError):
        return None


def version_key(v: str):
    """'2.5' < '2.5.1' < '2.10'. Fragmenty nieliczbowe porównywane jako tekst."""
    parts = []
    for p in v.strip().lstrip("vV").replace("-", ".").split("."):
        parts.append((0, int(p), "") if p.isdigit() else (1, 0, p))
    while parts and parts[-1] == (0, 0, ""):
        parts.pop()
    return parts


def is_newer(remote: str, local) -> bool:
    if not local:
        return True
    try:
        return version_key(remote) > version_key(local)
    except Exception:
        return remote.lstrip("vV") != local.lstrip("vV")


class UpdateError(Exception):
    pass


def http_get(url: str, accept: str = "application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=30)


def fetch_latest_release(cfg: dict) -> dict:
    """Najnowsze wydanie moda, czyli opublikowany Release z paczką oswiecenie*.zip.
    Wydania samego launchera (bez paczki moda) są pomijane."""
    url = f"{API_BASE}/repos/{cfg['github_repo']}/releases?per_page=30"
    try:
        with http_get(url) as r:
            releases = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("Nie znaleziono repozytorium moda na GitHubie "
                              "(sprawdź, czy jest publiczne).")
        if e.code == 403:
            raise UpdateError("GitHub chwilowo ogranicza liczbę zapytań. Spróbuj za kilka minut.")
        raise UpdateError(f"Błąd serwera GitHub ({e.code}).")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise UpdateError("Brak połączenia z internetem lub z GitHubem.")

    prefix = cfg["asset_prefix"].lower()
    found = []
    for rel in releases if isinstance(releases, list) else []:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        for a in rel.get("assets", []):
            name = a.get("name", "").lower()
            if name.startswith(prefix + "-") and name.endswith(".zip"):
                found.append({"version": str(rel.get("tag_name", "")).lstrip("vV"),
                              "url": a["browser_download_url"],
                              "size": int(a.get("size") or 0),
                              "name": a["name"]})
                break
    if not found:
        raise UpdateError("Autor nie opublikował jeszcze żadnej wersji moda.")
    try:
        return max(found, key=lambda r: version_key(r["version"]))
    except TypeError:
        return found[0]


def download(url: str, dest: Path, expected_size: int, progress) -> None:
    try:
        with http_get(url, accept="application/octet-stream") as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or expected_size or 0)
            done = 0
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise UpdateError(f"Pobieranie przerwane: {e}")
    if expected_size and dest.stat().st_size != expected_size:
        raise UpdateError("Pobrany plik ma nieprawidłowy rozmiar — spróbuj ponownie.")


def extract_mod(zip_path: Path, dest: Path, mod_name: str) -> str:
    """Rozpakowuje paczkę do dest. Akceptuje mod.json w korzeniu zipa
    albo w jednym folderze nadrzędnym. Zwraca wersję z mod.json."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise UpdateError("Pobrany plik nie jest poprawnym archiwum ZIP.")
    with zf:
        if zf.testzip() is not None:
            raise UpdateError("Archiwum jest uszkodzone.")
        names = zf.namelist()
        if "mod.json" in names:
            prefix = ""
        else:
            tops = {n.split("/")[0] for n in names if "/" in n}
            if len(tops) == 1 and f"{next(iter(tops))}/mod.json" in names:
                prefix = next(iter(tops)) + "/"
            else:
                raise UpdateError("W paczce brakuje pliku mod.json.")

        meta = json.loads(zf.read(prefix + "mod.json").decode("utf-8-sig"))
        if meta.get("name") != mod_name:
            raise UpdateError(f"Paczka zawiera moda „{meta.get('name')}”, a nie „{mod_name}”.")

        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        root = dest.resolve()
        for info in zf.infolist():
            if not info.filename.startswith(prefix) or info.filename == prefix:
                continue
            rel = info.filename[len(prefix):]
            target = (dest / rel).resolve()
            if root != target and root not in target.parents:
                raise UpdateError("Paczka zawiera niebezpieczne ścieżki — przerwano.")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
        return str(meta.get("version", ""))


def swap_in(new_dir: Path, mod_dir: Path) -> None:
    """Podmienia folder moda; przy błędzie przywraca poprzednią wersję."""
    old = mod_dir.with_name("." + mod_dir.name + ".stara")
    if old.exists():
        shutil.rmtree(old)
    if mod_dir.exists():
        try:
            os.rename(mod_dir, old)
        except OSError:
            raise UpdateError("Nie można podmienić folderu moda. Zamknij 0 A.D. i okna "
                              "Eksploratora z tym folderem, poczekaj na synchronizację OneDrive "
                              "i spróbuj ponownie.")
    try:
        os.rename(new_dir, mod_dir)
    except OSError:
        if old.exists():
            os.rename(old, mod_dir)
        raise UpdateError("Nie udało się zainstalować nowej wersji — przywrócono poprzednią.")
    shutil.rmtree(old, ignore_errors=True)


def is_author_copy(mod_dir: Path) -> bool:
    """Pliki, które są tylko w folderze roboczym autora, nigdy w paczce dla graczy."""
    if (mod_dir / ".git").exists() or (mod_dir / "CLAUDE.md").exists():
        return True
    return any(mod_dir.glob("_narzedzia_*"))


def game_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pyrogenesis.exe", "/NH"],
                             capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return "pyrogenesis.exe" in out.lower()
    except OSError:
        return False


def install_update(cfg: dict, mods_dir: Path, release: dict, progress, status) -> str:
    mods_dir.mkdir(parents=True, exist_ok=True)
    name = cfg["mod_name"]
    zip_path = mods_dir / f".{name}-pobieranie.zip"
    new_dir = mods_dir / f".{name}.nowa"
    try:
        status(f"Pobieranie {release['name']}…")
        download(release["url"], zip_path, release["size"], progress)
        status("Rozpakowywanie…")
        version = extract_mod(zip_path, new_dir, name)
        status("Instalowanie…")
        swap_in(new_dir, mods_dir / name)
        return version
    finally:
        try:
            zip_path.unlink()
        except OSError:
            pass
        shutil.rmtree(new_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Interfejs
# ---------------------------------------------------------------------------
class LauncherApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.root = root
        self.cfg = load_config()
        self.settings = load_settings()
        self.mods_dir = Path(self.settings.get("mods_dir") or default_mods_dir())
        self.release = None
        self.busy = False
        self.q = queue.Queue()

        root.title("Oświecenie — launcher")
        root.resizable(False, False)
        frm = ttk.Frame(root, padding=16)
        frm.grid()

        ttk.Label(frm, text="Epoka Oświecenia", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frm, text="mod do 0 A.D. Release 28").grid(row=1, column=0, columnspan=3, sticky="w")

        self.local_var = tk.StringVar()
        self.remote_var = tk.StringVar(value="Najnowsza wersja: sprawdzam…")
        self.status_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.local_var).grid(row=2, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Label(frm, textvariable=self.remote_var).grid(row=3, column=0, columnspan=3, sticky="w")

        self.bar = ttk.Progressbar(frm, length=380, mode="determinate")
        self.bar.grid(row=4, column=0, columnspan=3, pady=(12, 4))
        ttk.Label(frm, textvariable=self.status_var, wraplength=380).grid(
            row=5, column=0, columnspan=3, sticky="w")

        self.btn_check = ttk.Button(frm, text="Sprawdź", command=self.check)
        self.btn_update = ttk.Button(frm, text="Aktualizuj", command=lambda: self.update(False))
        self.btn_play = ttk.Button(frm, text="Graj", command=self.play)
        self.btn_check.grid(row=6, column=0, pady=(12, 0), sticky="we")
        self.btn_update.grid(row=6, column=1, pady=(12, 0), padx=6, sticky="we")
        self.btn_play.grid(row=6, column=2, pady=(12, 0), sticky="we")

        ttk.Button(frm, text="Ustaw ścieżkę do gry…", command=self.pick_game).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Label(frm, text=f"v{LAUNCHER_VERSION}", foreground="gray").grid(row=7, column=2, sticky="e")

        self.refresh_local()
        self.root.after(100, self.poll)
        self.check()

    # -- pomocnicze -------------------------------------------------------
    @property
    def mod_dir(self) -> Path:
        return self.mods_dir / self.cfg["mod_name"]

    def ui(self, fn, *args):
        """Wywołanie z wątku roboczego — wykona się w wątku interfejsu."""
        self.q.put((fn, args))

    def poll(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_check, self.btn_play):
            b.configure(state=state)
        can_update = not busy and self.release is not None and \
            is_newer(self.release["version"], read_local_version(self.mod_dir))
        self.btn_update.configure(state="normal" if can_update else "disabled")

    def refresh_local(self):
        v = read_local_version(self.mod_dir)
        self.local_var.set(f"Zainstalowana wersja: {v}" if v else "Zainstalowana wersja: brak moda")

    def progress(self, done, total):
        def apply():
            if total:
                self.bar.configure(mode="determinate", maximum=total, value=done)
                self.status_var.set(f"Pobieranie… {done / 1048576:.1f} / {total / 1048576:.1f} MB")
        self.ui(apply)

    # -- akcje ------------------------------------------------------------
    def check(self):
        if self.busy:
            return
        self.set_busy(True)
        self.status_var.set("Sprawdzanie aktualizacji…")

        def work():
            try:
                rel = fetch_latest_release(self.cfg)
                self.ui(self.on_checked, rel, None)
            except UpdateError as e:
                self.ui(self.on_checked, None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def on_checked(self, rel, err):
        self.release = rel
        if err:
            self.remote_var.set("Najnowsza wersja: nieznana")
            self.status_var.set(err)
        else:
            self.remote_var.set(f"Najnowsza wersja: {rel['version']}")
            if is_newer(rel["version"], read_local_version(self.mod_dir)):
                self.status_var.set("Dostępna jest aktualizacja.")
            else:
                self.status_var.set("Masz najnowszą wersję.")
        self.set_busy(False)

    def update(self, then_play: bool):
        from tkinter import messagebox
        if self.busy or not self.release:
            return
        if game_running():
            messagebox.showwarning("Gra jest uruchomiona", "Zamknij 0 A.D. przed aktualizacją moda.")
            return
        if is_author_copy(self.mod_dir):
            if not messagebox.askyesno(
                    "Kopia robocza autora",
                    "Ten folder moda wygląda na kopię roboczą autora "
                    "(zawiera CLAUDE.md, narzędzia lub repozytorium git).\n"
                    "Aktualizacja zastąpi wszystkie pliki w tym folderze i usunie te, "
                    "których nie ma w paczce.\n\nKontynuować?",
                    default="no", icon="warning"):
                return
        self.set_busy(True)
        self.bar.configure(value=0)

        def work():
            try:
                v = install_update(self.cfg, self.mods_dir, self.release, self.progress,
                                   lambda s: self.ui(self.status_var.set, s))
                self.ui(self.on_updated, v, None, then_play)
            except (UpdateError, OSError) as e:
                self.ui(self.on_updated, None, str(e), False)
        threading.Thread(target=work, daemon=True).start()

    def on_updated(self, version, err, then_play):
        from tkinter import messagebox
        self.refresh_local()
        self.set_busy(False)
        if err:
            self.status_var.set(err)
            messagebox.showerror("Błąd aktualizacji", err)
            return
        self.status_var.set(f"Zainstalowano wersję {version}.")
        if then_play:
            self.launch()

    def pick_game(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Wskaż plik pyrogenesis.exe (folder 0 A.D.\\binaries\\system)",
            filetypes=[("pyrogenesis.exe", "pyrogenesis.exe"), ("Programy", "*.exe")])
        if path:
            self.settings["game_exe"] = path
            save_settings(self.settings)
            return Path(path)
        return None

    def play(self):
        from tkinter import messagebox
        if self.busy:
            return
        local = read_local_version(self.mod_dir)
        if self.release and is_newer(self.release["version"], local):
            ans = messagebox.askyesnocancel(
                "Dostępna aktualizacja",
                f"Dostępna jest wersja {self.release['version']} (masz: {local or 'brak'}).\n"
                "W grze wieloosobowej wszyscy gracze muszą mieć tę samą wersję moda.\n\n"
                "Zaktualizować przed uruchomieniem?")
            if ans is None:
                return
            if ans:
                self.update(True)
                return
        if not local:
            messagebox.showerror("Brak moda", "Mod nie jest zainstalowany. Kliknij „Aktualizuj”.")
            return
        self.launch()

    def launch(self):
        from tkinter import messagebox
        exe = find_game_exe(self.settings) or self.pick_game()
        if not exe:
            return
        try:
            subprocess.Popen([str(exe)] + list(self.cfg["game_args"]), cwd=str(Path(exe).parent))
            self.root.after(1500, self.root.destroy)
        except OSError as e:
            messagebox.showerror("Nie udało się uruchomić gry", str(e))


def main():
    import tkinter as tk
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # ostre napisy na ekranach HiDPI
        except Exception:
            pass
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
