#!/usr/bin/env python3

import argparse
import os
import sys

from chomikuj import ChomikujDownloader, ChomikujUploader
from chomikuj.common import DEBUG, ChomikujError, load_default_env
from chomikuj.i18n import get_i18n
from chomikuj.terminal_ui import TerminalUi


def normalize_argv(argv):
    if not argv:
        return argv
    if argv[0] in ("download", "upload", "-h", "--help"):
        return argv
    return ["download"] + argv


def normalize_threads(value):
    return max(1, int(value or 1))


def build_parser(i18n):
    parser = argparse.ArgumentParser(
        prog="chomikuj_magic_command_line.py",
        description=i18n("cli.description"),
        epilog=i18n("cli.epilog"),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help=i18n("cli.download.help"))
    download.add_argument("urls", nargs="+", help=i18n("cli.download.urls"))
    download.add_argument("-o", "--output", default=os.getcwd(), help=i18n("cli.download.output"))
    download.add_argument("-t", "--threads", type=int, default=5, help=i18n("cli.download.threads"))
    download.add_argument("--flatten", action="store_true", help=i18n("cli.download.flatten"))
    download.add_argument("--keep-original-names", action="store_true", help=i18n("cli.download.keep_original_names"))
    download.add_argument("-v", "--debug", action="store_true", help=i18n("cli.debug"))

    upload = commands.add_parser("upload", help=i18n("cli.upload.help"))
    upload.add_argument("paths", nargs="+", help=i18n("cli.upload.paths"))
    upload.add_argument("--folder", default="", help=i18n("cli.upload.folder"))
    upload.add_argument("-t", "--threads", type=int, default=2, help=i18n("cli.upload.threads"))
    upload.add_argument("-v", "--debug", action="store_true", help=i18n("cli.debug"))
    return parser


def run_cli(argv, script_path):
    i18n = get_i18n("en")
    parser = build_parser(i18n)
    args = parser.parse_args(normalize_argv(argv))
    if args.command == "download":
        args.threads = normalize_threads(args.threads)
    elif args.command == "upload":
        args.threads = normalize_threads(args.threads)
    ui = TerminalUi(
        download_slots=args.threads if args.command == "download" else 0,
        live=not getattr(args, "debug", False),
        i18n=i18n,
    )
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
                keep_original_names=args.keep_original_names,
                i18n=i18n,
            )
            for url in args.urls:
                downloader.handle_url(url)
            downloader.wait()
        else:
            uploader = ChomikujUploader(
                username,
                password,
                max_threads=args.threads,
                debug=args.debug or DEBUG,
                password_provider=ui.password,
                status_sink=ui,
                debug_hook=ui.debug,
                i18n=i18n,
            )
            uploader.upload_files(args.paths, folder=args.folder)
    except KeyboardInterrupt:
        error = i18n("cli.interrupted")
    except ChomikujError as exc:
        error = str(exc)
    finally:
        ui.finish()
    if error:
        ui.error(error)
        sys.exit(1)


def main(argv=None):
    run_cli(list(sys.argv[1:] if argv is None else argv), __file__)


if __name__ == "__main__":
    main()
