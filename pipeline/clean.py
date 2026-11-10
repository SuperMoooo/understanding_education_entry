"""Clean the extracted workbook (data/interim) into the analysis workbook (data/processed).

Every rule is logged (sheet, rule, rows/columns affected) to the sheet `limpeza_log`
so the cleaning can be described and defended in the report.

Rules
  1. Keep only the degrees in scope (CTeSP, Licenciatura); drop master's etc.
  2. Harmonise labels: "Licenciatura 1.º ciclo" -> "Licenciatura".
  3. Harmonise columns renamed between InfoCursos editions (RENAMES below).
  4. Merge sheets that changed name (Idades -> Inscritos por Idade).
  5. Reshape sheets with the year in the column name to long format
     (one row per course x year) and keep the value from the newest edition.
  6. Put percentages/percentiles on a 0-100 scale.
  7. Drop rows where every indicator is empty (InfoCursos suppresses small/new courses).
  8. Drop columns that are completely empty; drop exact duplicate rows.
  9. Flag (do not drop) small samples: n <= config.MAX_N_PEQUENA -> amostra_pequena = True.
"""

from __future__ import annotations

import re

import pandas as pd

from . import config

GRAU_MAP = {"Licenciatura 1.º ciclo": "Licenciatura"}
# older editions write some labels without accents
LABEL_MAP = {
    "Natureza": {"Publico": "Público", "Privado": "Privado"},
    "TipoEnsino": {"Politecnico": "Politécnico", "Universitario": "Universitário"},
}
GRAUS_OK = {"CTeSP", "Licenciatura"}

# old name -> current name (InfoCursos editions up to 2021 used the old names)
RENAMES = {
    "Situacao Apos 1 Ano": {
        "PercentagemAindaInscritosCurso": "PercentagemInscritosMesmoEstabelecimentoCurso",
        "PercentagemOutroCursoOutroEstabelecimento": "PercentagemNoutroEstabelecimento",
    },
}
SHEET_ALIASES = {"Idades": "Inscritos por Idade"}

# sheets whose year lives in the column name: {sheet: [(regex, metric name)]}
WIDE = {
    "Numero Inscritos": [(r"^(\d{4}/\d{4})$", "NumeroInscritos")],
    "Percentil Entrada": [
        (r"^PercentilMedio(\d{4})$", "PercentilMedio"),
        (r"^NotaIngressoMedia(\d{4})$", "NotaIngressoMedia"),
        (r"^NumeroMatriculadosCNA(\d{4})$", "NumeroMatriculadosCNA"),
    ],
}
DESEMP_RX = r"^NumeroDiplomadosDesempregados"

ID_COLS = ["Estabelecimento", "CodigoEstabelecimento", "UnidadeOrganica",
           "CodigoUnidadeOrganica", "Natureza", "TipoEnsino", "NomeCurso", "CodigoCurso", "Grau"]
DROP_ALWAYS = ["Observações", "Total"]  # empty notes; "Total" is a sum of a moving window


class Log:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, sheet: str, rule: str, n: int, detail: str = "") -> None:
        if n:
            self.rows.append({"folha": sheet, "regra": rule, "afetados": n, "detalhe": detail})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["folha", "regra", "afetados", "detalhe"])


def _indicator_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if c not in ID_COLS and c != "edicao" and pd.api.types.is_numeric_dtype(df[c])]


def _size_col(df: pd.DataFrame) -> str | None:
    return next((c for c in df.columns if c.startswith("Numero")), None)


def _scope(df: pd.DataFrame, sheet: str, log: Log) -> pd.DataFrame:
    for col, mapping in LABEL_MAP.items():
        if col in df:
            before = df[col].copy()
            df[col] = df[col].replace(mapping)
            log.add(sheet, f"2 harmonizar {col}", int((before != df[col]).sum()), str(mapping))
    if "Grau" not in df:
        return df
    before = df["Grau"].copy()
    df["Grau"] = df["Grau"].replace(GRAU_MAP)
    log.add(sheet, "2 harmonizar Grau", int((before != df["Grau"]).sum()), str(GRAU_MAP))
    keep = df["Grau"].isin(GRAUS_OK)
    log.add(sheet, "1 fora do âmbito (grau)", int((~keep).sum()),
            ", ".join(sorted(before[~keep].dropna().unique())))
    return df[keep]


def _to_long(df: pd.DataFrame, sheet: str, log: Log) -> pd.DataFrame:
    """Wide year columns -> one row per course x ano; newest edition wins."""
    parts = []
    for rx, metric in WIDE[sheet]:
        cols = [c for c in df.columns if re.match(rx, c)]
        if not cols:
            continue
        m = df.melt(id_vars=["edicao", *[c for c in ID_COLS if c in df]], value_vars=cols,
                    var_name="ano", value_name=metric).dropna(subset=[metric])
        m["ano"] = m["ano"].str.extract(rx, expand=False)
        parts.append(m)
    if not parts:
        return df
    keys = ["CodigoUnidadeOrganica", "CodigoCurso", "Grau", "ano"]
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on=[*out.columns.intersection(p.columns)], how="outer")
    n0 = len(out)
    out = out.sort_values("edicao").groupby(keys, as_index=False, dropna=False).last()
    log.add(sheet, "5 formato longo (curso x ano)", n0 - len(out),
            "linhas repetidas entre edições removidas; fica a edição mais recente")
    return out.rename(columns={"edicao": "edicao_fonte"})


def _scale(df: pd.DataFrame, sheet: str, log: Log) -> pd.DataFrame:
    """Percentiles come as 0-1 in the source -> 0-100, like the percentages.
    Values outside the valid range are source errors: set to empty and logged."""
    for c in [c for c in df.columns if c.startswith("PercentilMedio")]:
        bad = df[c].notna() & ~df[c].between(0, 1)
        log.add(sheet, "6 valor inválido -> vazio", int(bad.sum()), f"{c} fora de 0-1")
        df.loc[bad, c] = None
        df[c] = df[c] * 100
        log.add(sheet, "6 escala 0-1 -> 0-100", int(df[c].notna().sum()), c)
    for c in [c for c in df.columns if c.startswith(("Percentagem", "Taxa"))]:
        bad = df[c].notna() & ~df[c].between(0, 100)
        log.add(sheet, "6 valor inválido -> vazio", int(bad.sum()), f"{c} fora de 0-100")
        df.loc[bad, c] = None
    return df


def clean_infocursos(name: str, df: pd.DataFrame, log: Log) -> pd.DataFrame:
    sheet = name.removeprefix("ic_")
    df = df.copy()
    df = _scope(df, sheet, log)

    ren = {k: v for k, v in RENAMES.get(sheet, {}).items() if k in df}
    for old, new in ren.items():
        df[new] = df[new].fillna(df[old]) if new in df else df[old]
        log.add(sheet, "3 harmonizar colunas", int(df[old].notna().sum()), f"{old} -> {new}")
    df = df.drop(columns=list(ren))

    desemp = [c for c in df.columns if re.match(DESEMP_RX, c)]
    if len(desemp) > 1 or (desemp and desemp[0] != "NumeroDiplomadosDesempregados"):
        df["NumeroDiplomadosDesempregados"] = df[desemp].bfill(axis=1).iloc[:, 0]
        df = df.drop(columns=[c for c in desemp if c != "NumeroDiplomadosDesempregados"])
        log.add(sheet, "3 harmonizar colunas", len(desemp),
                "NumeroDiplomadosDesempregados (média ...) -> NumeroDiplomadosDesempregados")

    if sheet in WIDE:
        df = _to_long(df, sheet, log)
        if "NumeroInscritos" in df:
            zero = df["NumeroInscritos"] == 0
            log.add(sheet, "7 anos com 0 inscritos (curso ainda não existia)", int(zero.sum()))
            df = df[~zero]
    df = _scale(df, sheet, log)

    ind = [c for c in _indicator_cols(df) if not c.startswith("Numero")]
    if ind:
        empty = df[ind].isna().all(axis=1)
        log.add(sheet, "7 sem indicadores (suprimido na fonte)", int(empty.sum()))
        df = df[~empty]

    drop = [c for c in df.columns if c in DROP_ALWAYS or df[c].isna().all()]
    log.add(sheet, "8 colunas vazias/removidas", len(drop), ", ".join(drop))
    df = df.drop(columns=drop)
    n0 = len(df)
    df = df.drop_duplicates()
    log.add(sheet, "8 linhas duplicadas", n0 - len(df))

    n = _size_col(df)
    if n:
        df["amostra_pequena"] = df[n] <= config.MAX_N_PEQUENA
        log.add(sheet, f"9 sinalizar n <= {config.MAX_N_PEQUENA}", int(df["amostra_pequena"].sum()),
                f"coluna {n}; não removidas")
    return df.reset_index(drop=True)


def clean_dgeec(name: str, df: pd.DataFrame, log: Log) -> pd.DataFrame:
    df = df.copy()
    drop = [c for c in ("pagina", "verificar") if c in df and (c == "pagina" or df[c].isna().all())]
    df = df.drop(columns=drop)
    if "n_diplomados" in df:
        df["amostra_pequena"] = df["n_diplomados"] <= config.MAX_N_PEQUENA
        log.add(name, f"9 sinalizar n <= {config.MAX_N_PEQUENA}", int(df["amostra_pequena"].sum()))
    if "ano_letivo_diploma" in df:
        miss = df["ano_letivo_diploma"].isna()
        log.add(name, "ano por confirmar no PDF", int(miss.sum()))
    return df


def clean(sheets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    log = Log()
    # rule 4: merge renamed sheets before cleaning
    for old, new in SHEET_ALIASES.items():
        o, n = f"ic_{old}", f"ic_{new}"
        if o in sheets:
            sheets[n] = pd.concat([sheets.pop(o), sheets.get(n)], ignore_index=True)
            log.add(new, "4 juntar folha renomeada", 1, f"{old} -> {new}")

    out: dict[str, pd.DataFrame] = {}
    for name, df in sheets.items():
        if name.startswith("ic_cmp_"):
            d = _scope(df.copy(), name, log)
            out[name] = d.reset_index(drop=True)
        elif name.startswith("ic_"):
            out[name] = clean_infocursos(name, df, log)
        elif name.startswith("dg_") and not name.endswith("_todas"):
            out[name] = clean_dgeec(name, df, log)
        elif name == "fontes":
            out[name] = df
        # dg_*_todas is an audit sheet: stays in data/interim only
    out["limpeza_log"] = log.frame()
    return out
