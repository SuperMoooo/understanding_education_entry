"""Command line:

  uv run python -m pipeline              fetch (new files only) + build + clean
  uv run python -m pipeline fetch        1. only download            -> data/raw/
  uv run python -m pipeline build        2. extract IPT rows         -> data/interim/
  uv run python -m pipeline clean        3. clean for analysis       -> data/processed/
  uv run python -m pipeline fetch --force          re-download everything
  uv run python -m pipeline fetch --only infocursos dgeec_ctesp_2020_21
"""

import argparse

from . import build, clean, config, fetch


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("step", nargs="?", default="all", choices=["all", "fetch", "build", "clean"])
    ap.add_argument("--force", action="store_true", help="re-download files already on disk")
    ap.add_argument("--only", nargs="+", help="source ids from sources.csv")
    a = ap.parse_args()
    if a.step in ("all", "fetch"):
        fetch.fetch_all(force=a.force, only=a.only)
    if a.step in ("all", "build"):
        build.write(build.build())
    if a.step in ("all", "clean"):
        build.write(clean.clean(build.read()), config.OUTPUT_XLSX)


if __name__ == "__main__":
    main()
