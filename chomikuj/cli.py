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
        description="Download and upload files through the new Chomikuj mobile API.",
        epilog="Login and password are read from .env (USERNAME, PASSWORD) in the current directory, and if it is missing then from the script directory. If they are still missing the program will ask for them interactively.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="Download files and folders from chomikuj.pl links.")
    download.add_argument("urls", nargs="+", help="One or more chomikuj.pl links to download.")
    download.add_argument("-o", "--output", default=os.getcwd(), help="Destination directory. Default: current directory.")
    download.add_argument("-t", "--threads", type=int, default=5, help="Number of concurrent downloads. Default: 5.")
    download.add_argument("--flatten", action="store_true", help="Do not recreate the initial URL tree. Files go directly into the destination directory.")
    download.add_argument("-v", "--debug", action="store_true", help="Print API request debug logs.")

    upload = commands.add_parser("upload", help="Upload local files or folders to your account.")
    upload.add_argument("paths", nargs="+", help="Local files or folders to upload. Directories are uploaded recursively.")
    upload.add_argument("--folder", default="", help="Remote folder path on your account or a folder URL. Default: root directory.")
    upload.add_argument("-v", "--debug", action="store_true", help="Print API request debug logs.")
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
                flatten=args.flatten,
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
        error = "Interrupted by user."
    except ChomikujError as exc:
        error = str(exc)
    finally:
        ui.finish()
    if error:
        ui.error(error)
        sys.exit(1)
