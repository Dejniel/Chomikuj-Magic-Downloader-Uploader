#!/usr/bin/env python3

import argparse
import os
import sys

from . import ChomikujDownloader, ChomikujUploader
from .common import DEBUG, ChomikujError, load_default_env
from .terminal_ui import TerminalUi


def normalize_argv(argv):
    if not argv:
        return argv
    if argv[0] in ("download", "upload", "-h", "--help"):
        return argv
    return ["download"] + argv


def build_parser():
    parser = argparse.ArgumentParser(
        prog="chomikuj_magic_downloader_uploader.py",
        description="Pobiera i wysyla pliki przez nowe API mobilne Chomikuj.",
        epilog="Login i haslo sa brane z .env (USERNAME, PASSWORD) z biezacego katalogu, a jesli go tam nie ma to z katalogu skryptu. Gdy ich brakuje program zapyta o nie interaktywnie.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="Pobieranie plikow i folderow z linkow chomikuj.pl.")
    download.add_argument("urls", nargs="+", help="Jeden lub wiecej linkow z chomikuj.pl do pobrania.")
    download.add_argument("-o", "--output", default=os.getcwd(), help="Katalog docelowy. Domyslnie: biezacy katalog.")
    download.add_argument("-t", "--threads", type=int, default=5, help="Liczba rownoleglych pobran. Domyslnie: 5.")
    download.add_argument("-v", "--debug", action="store_true", help="Wypisz debug logi requestow API.")

    upload = commands.add_parser("upload", help="Upload lokalnych plikow lub katalogow na twoje konto.")
    upload.add_argument("paths", nargs="+", help="Lokalne pliki lub katalogi do wyslania. Katalogi sa wrzucane rekurencyjnie.")
    upload.add_argument("--folder", default="", help="Sciezka zdalnego folderu na twoim koncie albo URL folderu. Domyslnie: katalog glowny.")
    upload.add_argument("-v", "--debug", action="store_true", help="Wypisz debug logi requestow API.")
    return parser


def run_cli(argv, script_path):
    parser = build_parser()
    args = parser.parse_args(normalize_argv(argv))
    ui = TerminalUi(download_slots=getattr(args, "threads", 0), live=not getattr(args, "debug", False))
    env = load_default_env(script_path)
    username = env.get("USERNAME", "") or ui.login()
    password = env.get("PASSWORD", "") or ui.login_password()
    error = None
    try:
        if args.command == "download":
            os.makedirs(args.output, exist_ok=True)
            downloader = ChomikujDownloader(
                username,
                password,
                args.threads,
                args.output,
                args.debug or DEBUG,
                password_provider=ui.password,
                status_sink=ui,
                debug_hook=ui.debug,
            )
            for url in args.urls:
                downloader.handle_url(url)
            downloader.wait()
        else:
            uploader = ChomikujUploader(
                username,
                password,
                args.debug or DEBUG,
                password_provider=ui.password,
                status_sink=ui,
                debug_hook=ui.debug,
            )
            uploader.upload_files(args.paths, folder=args.folder)
    except KeyboardInterrupt:
        error = "Przerwano przez uzytkownika."
    except ChomikujError as exc:
        error = str(exc)
    finally:
        ui.finish()
    if error:
        ui.error(error)
        sys.exit(1)
