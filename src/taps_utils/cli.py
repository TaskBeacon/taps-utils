from __future__ import annotations

import argparse

from .cache import cache_root
from .contract_source import fetch_contracts, resolve_contracts_root


def contracts_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="taps-contracts")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("version")
    fetch.add_argument("--url", default=None)
    fetch.add_argument("--force", action="store_true")

    where = sub.add_parser("where")
    where.add_argument("version")
    where.add_argument("--contracts-root", default=None)

    sub.add_parser("cache-dir")

    ns = parser.parse_args(argv)
    if ns.command == "fetch":
        print(fetch_contracts(ns.version, url=ns.url, force=bool(ns.force)))
    elif ns.command == "where":
        print(resolve_contracts_root(ns.version, contracts_root=ns.contracts_root))
    elif ns.command == "cache-dir":
        print(cache_root())
