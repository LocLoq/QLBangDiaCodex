from __future__ import annotations

import argparse
import sys
from functools import partial

from normastore.application.demo_seed import seed_demo
from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.infrastructure.database.unit_of_work import UnitOfWork


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=25000)
    args = parser.parse_args()
    factory = bootstrap(Settings())
    created, target = seed_demo(partial(UnitOfWork, factory), args.orders)
    print(f"Đã seed {created} phiếu mock nhất quán (mục tiêu {target}).")


if __name__ == "__main__":
    main()
