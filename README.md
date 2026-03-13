# Chomikuj Magic 

Alternative desktop software klient for chomikuj.pl that include Downloader and Uploder, supports resursive folders download/uploadd, and works asynchronious on many file at the time. It replache ChomikujBox and other chomikuj.pl aps. Check the [huge list of supported funcionality](#funkcjonalnosci).
Now you can upload and dowload chomikuj.pl!
on Windows, Linux, and macOS as a standalone tool using chomikuj new json v3 api insted of old soap xml api

## We need you!
- This project is open source! Your small monthly support on [Buy Me a Coffee](https://buymeacoffee.com/dejniel) can make a real difference and help keep it going—even a one-time donation helps. Building and maintaining a project like this takes a lot of time; if you find it useful, please consider supporting it so I can keep improving it: [support the project](https://buymeacoffee.com/dejniel)
- If you're a developer, contributions and bug reports are always welcome—please jump in. Especially if you use or build on non-Linux systems, please consider contributing fixes or improvements

## Requirements
- Python 3.8+
- pip install -r requirements.txt
- jesli nie chcesz wpisywać hasla za każdym razem umiesc credensials w  `.env` w katalogu projektu:
```env
USERNAME=twoj_login
PASSWORD=twoje_haslo
```

## Quick start (GUI)
- If no arguments are provided, a GUI opens. You can download, upload with one button,
  choose a file, and work. Run with no arguments:
  ```
  python3 timiniprint.py
  ```
## Quick start (CLI)

Pobranie jednego pliku:

```bash
python3 chomikuj_magic_downloader_uploader.py download "https://chomikuj.pl/Topola10/GALERIA/GIF/gif/szesciany,4422213476.gif"
```

Pobranie całego folderu:

```bash
python3 chomikuj_magic_downloader_uploader.py download "https://chomikuj.pl/mariusz1900/Dokumenty"
```

Upload pliku do katalogu glownego:

```bash
python3 chomikuj_magic_downloader_uploader.py upload ./plik.txt
```

Upload katalogu lokalnego rekurencyjnie:

```bash
python3 chomikuj_magic_downloader_uploader.py upload ./moj_folder
```

Upload do wskazanego folderu na twoim koncie:

```bash
python3 chomikuj_magic_downloader_uploader.py upload ./plik.txt --folder "Dokumenty/Test"
```

Uzycie wiekszej ilosci workerow do downloadu/uploadu
TODO przyklad

wyswietlenie pomocy
TODO komenda

## Uwaga
- Theoretically, I support Windows, macOS, and Linux, but I test builds only on Ubuntu-like systems—if you need to run this elsewhere, please report issues or submit a fix :P
- Projekt jest opensouce i może używać niepublicznych api - nie ma żadncej gwaracji. Przy użyciu mogą zostać napiczone opłaty, nie kożystaj jeśli nie jesteś pewien co robisz **PROGRAM NIGDY NIE PYTA OSTRZEZENIA O WIELKOSCI POBIERANYCH FOLDEROW**

# dostepne unkcje
- logowanie do chomikuj
- pobieranie pojedynczych plików i całych folderów
- upload lokalnych plikow na swoje konto
- wznawianie pobierania prze pliki tymczasowe .part
- upload chunkowany , mozliwe wznowienie
- wrapper na inne fukcje api jeszcze nie wykorzystane

