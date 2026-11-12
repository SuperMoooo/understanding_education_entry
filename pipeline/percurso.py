"""Follow the same entry cohort through the course, to see *in which year* students leave.

InfoCursos has two sheets about the students who enrol in the 1st year for the 1st time:
  - "Situacao Apos 1 Ano": where they are 1 year later. Each edition pools TWO entry
    cohorts (label "2019/20_2018/19").
  - "Taxa de Conclusao": how many finished in N, N+1 and N+3 years (N = course length).
    Each edition has ONE entry cohort (e.g. 2019/2020).
Pooling two conclusion editions gives the same students as one situation edition, so the
two sheets are matched course by course (CodigoUnidadeOrganica x CodigoCurso x Grau).

One row per course x cohort pair, public polytechnics only (eh_instituicao marks the
institution). Every % is of the students who entered (weight NumeroNovosInscritos):
  PercentagemSaiuEnsinoSuperior1Ano  not found in higher education 1 year after entering
  PercentagemMudouCurso1Ano          moved to another course/institution during year 1
  PercentagemContinuou1Ano           still in the course (or already graduated) after 1 year
  PercentagemConclusao*              finished the course in N / N+1 / N+3 years (cumulative)
  PercentagemSaiuDepois1Ano          continued after year 1 but did not finish by N+3
                                     (= Continuou1Ano - ConclusaoTempoEsperadoMaisTresAnos,
                                     floored at 0: a few students not found after year 1
                                     come back and finish)
The conclusion rate does not count students who switched course later, nor the few still
enrolled after N+3 years: both end up in SaiuDepois1Ano.
Only courses whose cohorts all have a conclusion row are kept, so the counts match
(NumeroNovosInscritos == NumeroInscritosConclusao).
"""

from __future__ import annotations

import re

import pandas as pd

from . import config
from .clean import GRAU_MAP, GRAUS_OK, LABEL_MAP, RENAMES

SIT, CONC = "Situacao Apos 1 Ano", "Taxa de Conclusao"
SHEETS = (SIT, CONC)
KEY = ["CodigoUnidadeOrganica", "CodigoCurso", "Grau"]
W_SIT = "NumeroInscritosPrimeiroAnoPrimeiraVez2Anos"
W_CONC = "NumeroInscritosPrimeiroAnoPrimeiraVez"
CONC_COLS = [
    "PercentagemConclusaoTempoEsperado",
    "PercentagemConclusaoTempoEsperadoMaisUmAno",
    "PercentagemConclusaoTempoEsperadoMaisTresAnos",
]
ID_COLS = ["Estabelecimento", "CodigoEstabelecimento", "UnidadeOrganica",
           "CodigoUnidadeOrganica", "Natureza", "TipoEnsino", "NomeCurso", "CodigoCurso", "Grau"]


def _ano(s: object) -> str | None:
    """'2018/2019' or '2018/19' -> '2018/19'."""
    m = re.fullmatch(r"(\d{4})/(\d{2}|\d{4})", str(s).strip())
    return f"{m[1]}/{m[2][-2:]}" if m else None


def _coortes(label: object) -> tuple[str, ...]:
    """'2019/20_2018/19' -> ('2018/19', '2019/20');  '2019/20_' -> ('2019/20',)."""
    return tuple(sorted({a for a in map(_ano, str(label).split("_")) if a}))


def _peers(df: pd.DataFrame) -> pd.DataFrame:
    """Public polytechnics, degrees in scope, labels harmonised across editions."""
    df = df.copy()
    for col, mapping in LABEL_MAP.items():
        if col in df:
            df[col] = df[col].replace(mapping)
    df["Grau"] = df["Grau"].replace(GRAU_MAP)
    return df[
        (df.get("TipoEnsino") == config.PEER_TIPO_ENSINO)
        & (df.get("Natureza") == config.PEER_NATUREZA)
        & df["Grau"].isin(GRAUS_OK)
    ]


def build(frames: dict[str, list[pd.DataFrame]]) -> pd.DataFrame | None:
    """frames: {sheet name: [one DataFrame per InfoCursos edition, all institutions]}."""
    if not frames.get(SIT) or not frames.get(CONC):
        return None
    sit = _peers(pd.concat(frames[SIT], ignore_index=True))
    for old, new in RENAMES.get(SIT, {}).items():
        if old in sit:
            sit[new] = sit[new].fillna(sit[old]) if new in sit else sit[old]
    sit = sit[sit[W_SIT].notna() & (sit[W_SIT] > 0)].copy()
    sit["coortes"] = sit["AnosInscritosPrimeiroAnoPrimeiraVez"].map(_coortes)

    conc = _peers(pd.concat(frames[CONC], ignore_index=True))
    conc = conc[conc[W_CONC].notna() & (conc[W_CONC] > 0)].copy()
    conc["coorte"] = conc["AnoInscritosPrimeiroAnoPrimeiraVez"].map(_ano)
    # a cohort could appear in more than one edition: keep the newest
    conc = conc.sort_values("edicao").drop_duplicates([*KEY, "coorte"], keep="last")
    for k in CONC_COLS:  # graduates (_n) and entrants (_w), only where the % was published
        ok = conc[k].notna()
        conc[f"{k}_n"] = (conc[k] * conc[W_CONC] / 100).where(ok)
        conc[f"{k}_w"] = conc[W_CONC].where(ok)
    rows = []
    for (ed, grau), g in sit.groupby(["edicao", "Grau"]):
        par = tuple(sorted({a for t in g["coortes"] for a in t}))
        c = conc[(conc["Grau"] == grau) & conc["coorte"].isin(par)]
        if c.empty:
            continue
        cp = c.groupby(KEY, as_index=False).agg(
            coortes_conc=("coorte", lambda x: tuple(sorted(x))),
            NumeroInscritosConclusao=(W_CONC, "sum"),
            edicoes_conclusao=("edicao", lambda x: "+".join(map(str, sorted(x)))),
            DuracaoCurso=("DuracaoCurso", "first"),
            **{f"{k}_{s}": (f"{k}_{s}", "sum") for k in CONC_COLS for s in ("n", "w")},
        )
        for k in CONC_COLS:  # pooled over the cohorts; 0/0 -> NaN when never published
            cp[k] = 100 * cp[f"{k}_n"] / cp[f"{k}_w"].replace(0, float("nan"))
        m = g.merge(cp[[*KEY, "coortes_conc", "NumeroInscritosConclusao", "edicoes_conclusao",
                        "DuracaoCurso", *CONC_COLS]], on=KEY, how="inner")
        # same students only: every cohort of the course in "Situacao" has its conclusion row
        # (a 4-year licenciatura has another cohort in the same conclusion edition)
        m = m[m["coortes"] == m["coortes_conc"]]
        if m.empty:
            continue
        out = m[[c for c in ID_COLS if c in m]].copy()
        out.insert(0, "edicao", ed)
        out.insert(1, "coortes", m["coortes"].map(" + ".join))
        out["edicoes_conclusao"] = m["edicoes_conclusao"]
        out["DuracaoCurso"] = m["DuracaoCurso"]
        out["NumeroNovosInscritos"] = m[W_SIT]
        out["NumeroInscritosConclusao"] = m["NumeroInscritosConclusao"]
        out["PercentagemSaiuEnsinoSuperior1Ano"] = m["PercentagemNaoEncontradosEnsinoSuperior"]
        out["PercentagemMudouCurso1Ano"] = (
            m["PercentagemOutroCursoMesmoEstabelecimento"].fillna(0)
            + m["PercentagemNoutroEstabelecimento"].fillna(0)
        )
        out["PercentagemContinuou1Ano"] = (
            m["PercentagemInscritosMesmoEstabelecimentoCurso"].fillna(0)
            + m["PercentagemDiplomadosCurso"].fillna(0)
        )
        for k in CONC_COLS:
            out[k] = m[k]
        # below 0 only when students not found after year 1 came back and finished
        out["PercentagemSaiuDepois1Ano"] = (
            out["PercentagemContinuou1Ano"] - out["PercentagemConclusaoTempoEsperadoMaisTresAnos"]
        ).clip(lower=0)
        # a course whose situation % were all suppressed has nothing to split
        sit_pct = ["PercentagemNaoEncontradosEnsinoSuperior",
                   "PercentagemInscritosMesmoEstabelecimentoCurso"]
        out = out[m[sit_pct].notna().any(axis=1).to_numpy()]
        rows.append(out)
    if not rows:
        return None
    res = pd.concat(rows, ignore_index=True)
    res["eh_instituicao"] = (
        (res["CodigoEstabelecimento"].astype(str).str.strip() == config.INSTITUTION_CODE)
        | res["Estabelecimento"].str.contains(config.INSTITUTION_NAME_REGEX)
    )
    return res.sort_values(["edicao", "Grau", "Estabelecimento", "NomeCurso"]).reset_index(drop=True)
