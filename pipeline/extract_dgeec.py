"""Extract numbers from the DGEEC "Prosseguimento de estudos" PDF reports.

The per-institution table lists, for each academic year, one row per public
institution, e.g.  "I. P. de Tomar 99 52% 6% 0% 42%".  The year label is a
merged cell whose text position is unreliable, so the year is assigned by
order: the institution's rows appear in the same order as the years in
"Tabela 1" (national series). The extractor checks that the counts match and
leaves the year empty if they do not, so a layout change is visible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pdfplumber

from . import config

COLUMNS = {
    "dgeec_ctesp": {
        "ies": ["n_diplomados", "pct_licenciatura_mesma_ies", "pct_licenciatura_outra_ies",
                "pct_outro_nivel", "pct_nao_encontrados"],
        "nacional": ["n_diplomados", "pct_ctesp", "pct_licenciatura", "pct_mestrado_integrado",
                     "pct_outro_nivel", "pct_nao_encontrados"],
    },
    "dgeec_licenciatura": {
        "ies": ["n_diplomados", "pct_pos_licenciatura_mesma_ies", "pct_pos_licenciatura_outra_ies",
                "pct_outro_nivel", "pct_nao_encontrados"],
        "nacional": ["n_diplomados", "pct_mestrado", "pct_doutoramento", "pct_especializacao",
                     "pct_outro_nivel", "pct_nao_encontrados"],
    },
}

YEAR = r"(\d{4}/\d{4})"
NUM = r"(\d{1,3}(?: \d{3})*|\d+)"  # "5 162" or "5162"
PCT = r"(\d+)%"


def _pages(path: Path) -> list[str]:
    with pdfplumber.open(path) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


def _num(s: str) -> int:
    return int(s.replace(" ", ""))


def _tabela1(text: str, n_pct: int) -> list[tuple]:
    start = text.find("Tabela 1")
    end = text.find("Tabela 2", start)
    if start < 0:
        return []
    block = text[start:end if end > 0 else None]
    rx = re.compile(rf"^{YEAR}\s+{NUM}" + rf"\s+{PCT}" * n_pct + r"\s*$", re.M)
    return [(m.group(1), _num(m.group(2)), *map(int, m.groups()[2:])) for m in rx.finditer(block)]


def extract(path: Path, parser: str, source_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (institution rows, national rows) from one report."""
    cols = COLUMNS[parser]
    pages = _pages(path)
    text = "\n".join(pages)

    nat = _tabela1(text, len(cols["nacional"]) - 1)
    years = [r[0] for r in nat]
    national = pd.DataFrame(nat, columns=["ano_letivo_diploma", *cols["nacional"]])

    rx = re.compile(rf"{config.INSTITUTION_NAME_REGEX}\s+{NUM}" + rf"\s+{PCT}" * 4)
    hits = []
    for pno, page in enumerate(pages, 1):
        for line in page.splitlines():
            m = rx.search(line)
            if m:
                hits.append((pno, _num(m.group(1)), *map(int, m.groups()[1:])))
    inst = pd.DataFrame(hits, columns=["pagina", *cols["ies"]])
    if len(hits) == len(years):
        inst.insert(0, "ano_letivo_diploma", years)
        inst["verificar"] = ""
    else:
        inst.insert(0, "ano_letivo_diploma", None)
        inst["verificar"] = f"{len(hits)} linhas vs {len(years)} anos: confirmar no PDF"
        print(f"  ! {source_id}: {len(hits)} institution rows but {len(years)} years in Tabela 1")

    for df in (inst, national):
        df["fonte"] = source_id
        df["relatorio_ate"] = max(years) if years else None
    return inst, national


def combine(frames: list[pd.DataFrame], value_cols: list[str]) -> pd.DataFrame:
    """One row per year, taken from the most recent report. Flags years where
    reports disagree."""
    if not frames:
        return pd.DataFrame()
    allrows = pd.concat(frames, ignore_index=True).dropna(subset=["ano_letivo_diploma"])
    allrows = allrows.sort_values(["ano_letivo_diploma", "relatorio_ate"])
    out = allrows.groupby("ano_letivo_diploma").tail(1).copy()
    disagree = (
        allrows.groupby("ano_letivo_diploma")[value_cols].nunique().gt(1).any(axis=1)
    )
    out["relatorios_discordam"] = out["ano_letivo_diploma"].map(disagree)
    return out.reset_index(drop=True)
