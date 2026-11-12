"""Turn the downloaded files into one Excel workbook for the institution.

Sheets (prefix ic_ = InfoCursos, dg_ = DGEEC):
  ic_<sheet>             institution rows of every InfoCursos sheet, all editions
  ic_cmp_<sheet>         latest edition: weighted % by public polytechnic x degree
  ic_Percurso Coorte     one entry cohort followed course by course (situation after year 1
                         + conclusion), every public polytechnic: see percurso.py
  dg_ctesp_ipt           CTeSP graduates' situation next year, institution, one row/year
  dg_ctesp_nacional      same, national
  dg_lic_ipt / dg_lic_nacional   licenciatura graduates (for comparison)
  dg_*_todas             every row from every report (to audit overlaps)
  fontes                 data/manifest.csv
"""

from __future__ import annotations

import csv
from collections import defaultdict

import pandas as pd

from . import config, extract_dgeec, extract_infocursos, percurso
from .fetch import load_sources


def _files_by_parser() -> dict[str, list[tuple[str, object]]]:
    """Map parser -> [(source_id, path)] using sources.csv + data/manifest.csv."""
    parser_of = {s.id: s.parser for s in load_sources() if s.enabled}
    out: dict[str, list] = defaultdict(list)
    if not config.MANIFEST_CSV.exists():
        raise FileNotFoundError("data/manifest.csv missing: run the fetch step first")
    with open(config.MANIFEST_CSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            p = parser_of.get(r["source_id"])
            path = config.ROOT / r["local_path"]
            if p and p != "none" and path.exists():
                out[p].append((r["source_id"], path))
    return out


def _sheet(name: str) -> str:
    bad = '[]:*?/\\'
    return "".join("_" if ch in bad else ch for ch in name)[:31]


def build() -> dict[str, pd.DataFrame]:
    files = _files_by_parser()
    sheets: dict[str, pd.DataFrame] = {}

    # --- InfoCursos -------------------------------------------------------
    per_sheet: dict[str, list[pd.DataFrame]] = defaultdict(list)
    all_rows: dict[str, list[pd.DataFrame]] = defaultdict(list)  # every institution
    latest: dict[str, pd.DataFrame] = {}
    latest_ed = -1
    for _sid, path in sorted(files.get("infocursos", []), key=lambda t: str(t[1])):
        if path.suffix.lower() != ".xlsx":
            continue
        print(f"  infocursos: {path.name}")
        wb = extract_infocursos.read_workbook(path)
        ed = extract_infocursos.edition_of(path) or 0
        for name, df in wb.items():
            per_sheet[name].append(df[extract_infocursos.is_institution(df)])
            if name in percurso.SHEETS:
                all_rows[name].append(df)
        if ed > latest_ed:
            latest_ed, latest = ed, wb
    for name, frames in per_sheet.items():
        sheets[_sheet(f"ic_{name}")] = pd.concat(frames, ignore_index=True)
    for name, df in latest.items():
        cmp = extract_infocursos.peer_comparison(df)
        if cmp is not None:
            sheets[_sheet(f"ic_cmp_{name}")] = cmp
    coorte = percurso.build(all_rows)
    if coorte is not None:
        sheets["ic_Percurso Coorte"] = coorte

    # --- DGEEC ------------------------------------------------------------
    for parser, short in (("dgeec_ctesp", "ctesp"), ("dgeec_licenciatura", "lic")):
        inst_frames, nat_frames = [], []
        for sid, path in files.get(parser, []):
            print(f"  {parser}: {sid}")
            inst, nat = extract_dgeec.extract(path, parser, sid)
            inst_frames.append(inst)
            nat_frames.append(nat)
        if not inst_frames:
            continue
        cols = extract_dgeec.COLUMNS[parser]
        sheets[f"dg_{short}_ipt"] = extract_dgeec.combine(inst_frames, cols["ies"])
        sheets[f"dg_{short}_nacional"] = extract_dgeec.combine(nat_frames, cols["nacional"])
        sheets[f"dg_{short}_ipt_todas"] = pd.concat(inst_frames, ignore_index=True)

    sheets["fontes"] = pd.read_csv(config.MANIFEST_CSV, dtype=str)
    return sheets


def write(sheets: dict[str, pd.DataFrame], xlsx=None) -> None:
    """Write sheets to an Excel workbook plus one CSV per sheet in the same folder."""
    xlsx = xlsx or config.INTERIM_XLSX
    xlsx.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name, index=False)
    for name, df in sheets.items():
        df.to_csv(xlsx.parent / f"{name}.csv", index=False, encoding="utf-8")
    print(f"wrote {xlsx.relative_to(config.ROOT)} ({len(sheets)} sheets) + CSVs")


def read(xlsx=None) -> dict[str, pd.DataFrame]:
    """Read a workbook written by `write` (codes kept as text)."""
    xlsx = xlsx or config.INTERIM_XLSX
    text = {c: str for c in ("CodigoEstabelecimento", "CodigoUnidadeOrganica", "CodigoCurso")}
    return pd.read_excel(xlsx, sheet_name=None, dtype=text)
