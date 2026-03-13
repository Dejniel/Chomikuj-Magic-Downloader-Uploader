#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys


def main(argv):
    if argv:
        from chomikuj.cli import run_cli

        run_cli(argv, __file__)
        return
    try:
        from chomikuj.gui import run_gui

        run_gui(__file__)
    except ModuleNotFoundError as exc:
        if exc.name != "tkinter":
            raise
        print("GUI wymaga modulu tkinter. Doinstaluj python3-tk albo uruchom program z parametrami CLI.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
