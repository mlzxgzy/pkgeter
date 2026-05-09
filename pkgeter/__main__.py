"""Entry point for `python -m pkgeter` and `pkgeter` CLI command."""

import sys


def main():
    from pkgeter.cli import run_cli
    run_cli()


if __name__ == "__main__":
    main()
