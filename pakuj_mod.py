# -*- coding: utf-8 -*-
"""
Pakuje folder moda do paczki wydania dla launchera.

Użycie (z wiersza poleceń):
    python pakuj_mod.py "C:\\Users\\...\\My Games\\0ad\\mods\\oswiecenie"

Tworzy obok skryptu plik oswiecenie-<wersja>.zip (wersja z mod.json),
z mod.json w korzeniu archiwum. Ten plik dołącza się do wydania na GitHubie.
"""
import fnmatch
import json
import sys
import zipfile
from pathlib import Path

POMIJANE_FOLDERY = {".git", ".github", "__pycache__", ".vscode", ".idea", "przygotowane"}
# Pliki robocze autora — nie trafiają do paczki dla graczy.
# Uwaga: archiwa .zip w folderze moda (np. oswiecenie_tekstury.zip) gra montuje
# jak zwykłe pliki, więc NIE są pomijane.
POMIJANE_PLIKI = ["*.bak", "*.tmp", "*.blend1", "Thumbs.db", "desktop.ini", ".DS_Store",
                  ".gitignore", "CLAUDE.md", "_narzedzia_*", "*.tar.gz", "*.py"]
# Pliki już skompresowane — pakowane bez ponownej kompresji (szybciej).
BEZ_KOMPRESJI = {".zip", ".ogg", ".png", ".dds", ".jpg", ".jpeg", ".gz"}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    mod = Path(sys.argv[1]).resolve()
    try:
        meta = json.loads((mod / "mod.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        print(f"Nie można odczytać {mod / 'mod.json'}: {e}")
        return 1
    name, version = meta.get("name"), meta.get("version")
    if not name or not version:
        print("mod.json musi zawierać pola \"name\" i \"version\".")
        return 1

    out = Path(__file__).resolve().parent / f"{name}-{version}.zip"
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(mod.rglob("*")):
            rel = path.relative_to(mod)
            if any(part in POMIJANE_FOLDERY for part in rel.parts):
                continue
            if path.is_dir() or any(fnmatch.fnmatch(path.name, p) for p in POMIJANE_PLIKI):
                continue
            typ = zipfile.ZIP_STORED if path.suffix.lower() in BEZ_KOMPRESJI else zipfile.ZIP_DEFLATED
            zf.write(path, rel.as_posix(), compress_type=typ)
            count += 1

    size = out.stat().st_size / 1048576
    print(f"Gotowe: {out.name} ({count} plików, {size:.1f} MB)")
    print()
    print("Dalej na GitHubie: Releases → Draft a new release")
    print(f"  Tag:     v{version}")
    print(f"  Załącz:  {out.name}")
    print("  Publish release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
