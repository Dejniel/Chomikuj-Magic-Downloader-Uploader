# Chomikuj Magic

Alternative [desktop client](https://github.com/Dejniel/Chomikuj-Magic-Downloader-Uploader/releases)  for **[chomikuj.pl](https://chomikuj.pl)** that includes a **Downloader** and **Uploader**, supports recursive folder download/upload, and works asynchronously on many files at the same time. It replaces ChomikujBox and other chomikuj.pl apps and it's **fast**. Check the [list of supported features](#available-features)

Now you can upload and download chomikuj.pl on **Windows, Linux, and macOS** as a standalone tool using Chomikuj's new JSON v3 API instead of the old SOAP XML API

![Chomikuj Magic Downloader Uploader LOGO Hamster](chomikuj_magic.png)

# We need you!

- This project is open source! Your small monthly support on [Buy Me a Coffee](https://buymeacoffee.com/dejniel) can make a real difference and help keep it going—even a one-time donation helps. Building and maintaining a project like this takes a lot of time; if you find it useful, please consider supporting it so I can keep improving it: [support the project](https://buymeacoffee.com/dejniel)
- If you're a developer, contributions and bug reports are always welcome—please jump in. Especially if you use or build on non-Linux systems, please consider contributing fixes or improvements

# Available features

- login to Chomikuj
- download single files and whole folders
- upload local files to your own account
- resume downloads through temporary `.part` files
- chunked upload, resume possible
- wrapper for other API functions not yet used

# Requirements

You can find the latest standalone executable files on the [releases page](https://github.com/Dejniel/Chomikuj-Magic-Downloader-Uploader/releases)
or you can build the project yourself.

## Manual building requirements

- Python 3.8+
- pip install -r requirements.txt
- (optional) if you do not want to enter the password every time, put credentials in `.env` in the project directory:
  ```env
  USERNAME=your_login
  PASSWORD=your_password
  ```
- (optional, GUI only) if `tkinter` is missing, install it from your system packages:
  Linux (Ubuntu/Debian): `sudo apt install python3-tk`
  macOS (Homebrew Python): `brew install python-tk`
  
# Quick start

If you use release binaries, run the executable directly without `python3`.
Examples below show how to run the source files from the project directory.

## Graphical user interface

You can download, upload with one button, choose a file, and work:

```bash
python3 chomikuj_magic_graphical.py
```

## Command line interface

Download a single file:

```bash
python3 chomikuj_magic_command_line.py download "https://chomikuj.pl/Emaus/materiały+audio/konferencje/ks_piotr_pawlukiewicz_mlodziez,21520803.mp3"
```

Download a whole folder:

```bash
python3 chomikuj_magic_command_line.py download "https://chomikuj.pl/RysunekSatyryczny/Zbigniew+Jujka"
```

Upload a file to the root directory:

```bash
python3 chomikuj_magic_command_line.py upload ./file.txt
```

Upload a local folder recursively:

```bash
python3 chomikuj_magic_command_line.py upload ./my_folder
```

Upload to a selected folder on your account:

```bash
python3 chomikuj_magic_command_line.py upload ./file.txt --folder "Documents/Test"
```

Use more download workers:

```bash
python3 chomikuj_magic_command_line.py download -t 8 "https://chomikuj.pl/Adam26121996/Tapety+na+komórkę/Śmieszne"
```

Show help:

```bash
python3 chomikuj_magic_command_line.py --help
```

# Warning

- Theoretically, I support Windows, macOS, and Linux, but I test builds only on Ubuntu-like systems—if you need to run this elsewhere, please report issues or submit a fix :P
- This project is open source and may use non-public APIs - there is no guarantee of anything. Charges may be applied while using it, so do not use it if you are not sure what you are doing. 
- **THE PROGRAM NEVER SHOWS A WARNING ABOUT THE SIZE OF DOWNLOADED FOLDERS**
