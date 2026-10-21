# Epoka Oświecenia — launcher

Launcher moda **Epoka Oświecenia (XVIII wiek)** do gry **0 A.D. Release 28**.
Sprawdza, czy jest nowa wersja moda, pobiera ją, instaluje i uruchamia grę z włączonym modem.

## Dla graczy

1. Wejdź w **[Releases](../../releases)** i pobierz `Oswiecenie-Launcher.exe`
   (z wydania „Launcher …”).
2. Uruchom plik. Za pierwszym razem Windows może pokazać
   „System Windows ochronił ten komputer” — kliknij **Więcej informacji → Uruchom mimo to**.
3. Gdy pojawi się nowa wersja, kliknij **Aktualizuj**, a potem **Graj**.
4. Jeśli launcher nie znajdzie gry, kliknij **Ustaw ścieżkę do gry…** i wskaż
   `pyrogenesis.exe` w folderze 0 A.D. (`binaries\system`).

W grze wieloosobowej wszyscy muszą mieć tę samą wersję moda — przed wspólną grą
niech każdy kliknie **Sprawdź**.

Mod instaluje się do `Dokumenty\My Games\0ad\mods\oswiecenie` (także gdy Dokumenty są w OneDrive).
Ustawienia launchera: `%LOCALAPPDATA%\OswiecenieLauncher\settings.json`.

## Dla autora: wydanie nowej wersji moda

1. Podbij `version` w `mod.json` moda (np. `2.12.3` → `2.12.4`).
2. Spakuj moda (potrzebny Python):

   ```
   python pakuj_mod.py "C:\Users\kubus\OneDrive\Dokumenty\My Games\0ad\mods\oswiecenie"
   ```

   Powstanie `oswiecenie-<wersja>.zip`. Skrypt pomija pliki robocze (`CLAUDE.md`,
   `_narzedzia_*.tar.gz`, folder `przygotowane`, pliki `.py`), a zostawia
   `oswiecenie_tekstury.zip`, bo gra go wczytuje.
3. Na GitHubie: **Releases → Draft a new release**
   - tag: `v2.12.4` (ta sama wersja co w `mod.json`),
   - załącz `oswiecenie-2.12.4.zip`,
   - **Publish release**.

Launcher bierze wydanie z najwyższym numerem wersji, które zawiera plik `oswiecenie-*.zip`.
Wydania oznaczone jako *pre-release* i szkice są pomijane, więc można ich używać do testów.

## Dla autora: nowa wersja launchera

Launcher buduje się sam w GitHub Actions (`.github/workflows/zbuduj-launcher.yml`):

- po każdej zmianie `oswiecenie_launcher.py` gotowy `.exe` jest w zakładce
  **Actions** → ostatni przebieg → **Artifacts**;
- żeby opublikować nową wersję dla graczy, podbij `LAUNCHER_VERSION` na początku
  `oswiecenie_launcher.py` (np. `1.0.0` → `1.0.1`) — workflow sam utworzy wydanie
  `launcher-v1.0.1` z dołączonym `.exe`. Wydania launchera nie są oznaczane jako „Latest”,
  a sam launcher je pomija przy szukaniu wersji moda.

Lokalnie można też zbudować `.exe` przez `build.bat`.
Własna ikona: dodaj plik `ikona.ico` do repozytorium.

## Pliki

| Plik | Do czego |
|---|---|
| `oswiecenie_launcher.py` | kod launchera (Python, tylko biblioteka standardowa) |
| `pakuj_mod.py` | pakuje folder moda do paczki wydania |
| `build.bat` | lokalne budowanie `.exe` (PyInstaller) |
| `.github/workflows/zbuduj-launcher.yml` | automatyczne budowanie `.exe` na GitHubie |
