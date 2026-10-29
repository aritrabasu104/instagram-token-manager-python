"""Credential-free package information; never accepts a token on argv."""

import argparse
import json

from . import __version__
from .http import CONTRACTS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["version", "list-apis"])
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
    else:
        print(
            json.dumps(
                {
                    "apis": [
                        dict(zip(("id", "method", "url", "fields", "kind"), row, strict=True))
                        for row in CONTRACTS
                    ],
                    "secret_exposed": False,
                }
            )
        )
    return 0
