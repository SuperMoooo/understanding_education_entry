"""Read InfoCursos yearly workbooks (Infocursos_YYYY.xlsx).

Every data sheet has a few title rows and then a header row that starts with
"Estabelecimento". The header row is detected instead of hard-coded so older
and future editions still work. Codes are kept as text (leading zeros).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from . import config

TEXT_COLS_PREFIX = ("Codigo",)
TEXT_COLS = {
    "Estabelecimento", "UnidadeOrganica", "Natureza", "TipoEnsino", "NomeCurso", "Grau",
    "AnosInscritosPrimeiroAnoPrimeiraVez", "AnoInscritosPrimeiroAnoPrimeiraVez", "AnoLetivo",
    "AnosLetivosDiplomados", "Fonte", "AmostraAceite", "DuracaoCurso",
}


def edition_of(path: Path) -> int | None:
    m = re.search(r"(\d{4})", path.stem)
    return int(m.group(1)) if m else None


def _header_row(raw: pd.DataFrame) -> int | None:
    for i in range(min(15, len(raw))):
        if "Estabelecimento" in raw.iloc[i].astype(str).str.strip().tolist():
            return i
    return None


def read_workbook(path: Path) -> dict[str, pd.DataFrame]:
    """Return {sheet_name: tidy DataFrame} for every data sheet in one edition."""
    out: dict[str, pd.DataFrame] = {}
    sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    for name, raw in sheets.items():
        h = _header_row(raw)
        if h is None:
            continue  # e.g. "Nota Técnica"
        df = raw.iloc[h + 1:].copy()
        df.columns = [str(c).strip() for c in raw.iloc[h]]
        df = df.loc[:, [c for c in df.columns if c and c != "nan"]]
        df = df.dropna(how="all")
        df = df[df["Estabelecimento"].notna()]
        for c in df.columns:
            if c in TEXT_COLS or c.startswith(TEXT_COLS_PREFIX):
                df[c] = df[c].str.strip()
            else:
                conv = pd.to_numeric(df[c], errors="coerce")
                # keep as text if the column is not really numeric (e.g. year labels)
                if conv.notna().sum() >= df[c].notna().sum() * 0.9:
                    df[c] = conv
        df.insert(0, "edicao", edition_of(path))
        out[name.strip()] = df.reset_index(drop=True)
    return out


def is_institution(df: pd.DataFrame) -> pd.Series:
    by_code = df.get("CodigoEstabelecimento", pd.Series("", index=df.index)).astype(str).str.strip()
    by_name = df["Estabelecimento"].astype(str).str.contains(config.INSTITUTION_NAME_REGEX, regex=True)
    return (by_code == config.INSTITUTION_CODE) | by_name


def _first_col(df: pd.DataFrame, prefix: str) -> str | None:
    return next((c for c in df.columns if c.startswith(prefix)), None)


def peer_comparison(df: pd.DataFrame) -> pd.DataFrame | None:
    """Weighted averages of the 'Percentagem*' columns by institution and degree,
    for public polytechnics. Weight = the first 'Numero*' column of the sheet."""
    pct = [c for c in df.columns if c.startswith("Percentagem")]
    w = _first_col(df, "Numero")
    if not pct or w is None:
        return None
    sub = df[
        (df.get("TipoEnsino") == config.PEER_TIPO_ENSINO)
        & (df.get("Natureza") == config.PEER_NATUREZA)
        & (df["Grau"].isin(config.GRAUS_COMPARACAO))
    ].copy()
    if sub.empty:
        return None
    sub = sub[sub[w].notna() & (sub[w] > 0)]
    rows = []
    for (est, grau), g in sub.groupby(["Estabelecimento", "Grau"]):
        row = {"edicao": g["edicao"].iat[0], "Estabelecimento": est, "Grau": grau,
               "n_cursos": len(g), w: g[w].sum()}
        for c in pct:
            ok = g[c].notna()
            row[c] = (g.loc[ok, c] * g.loc[ok, w]).sum() / g.loc[ok, w].sum() if ok.any() else None
        rows.append(row)
    res = pd.DataFrame(rows)
    res["eh_instituicao"] = res["Estabelecimento"].str.contains(config.INSTITUTION_NAME_REGEX)
    return res.sort_values(["Grau", "Estabelecimento"]).reset_index(drop=True)
