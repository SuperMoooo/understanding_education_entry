"""Dashboard: CTeSP no Politécnico de Tomar (IPT / UPTomar).

Correr (na raiz do projeto):
    uv run python -m pipeline          # gera data/processed/ (se ainda não existir)
    uv run streamlit run outputs/app.py

Só lê os CSVs de data/processed/. Um separador por pergunta de questions.txt, pela ordem
do percurso do aluno: quem entra -> quantos entram -> quantos abandonam -> quantos concluem
-> quantos prosseguem -> com que nota saem.
"""

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
MAX_N_PEQUENA = 5  # igual a pipeline/config.py; quem tem n <= isto vem marcado em amostra_pequena
COR_IPT, COR_OUTROS = "#74BC1F", "#9aa5b1"
CORES_GRAU = alt.Scale(domain=["CTeSP", "Licenciatura"], range=["#74BC1F", "#1f77b4"])
TEXT = {
    c: str for c in ("CodigoCurso", "CodigoUnidadeOrganica", "CodigoEstabelecimento")
}
CURSO = [
    "edicao",
    "CodigoUnidadeOrganica",
    "CodigoCurso",
]  # chave de um curso numa edição

# Situação 1 ano após entrar (InfoCursos), por ordem lógica
SITUACAO = {
    "PercentagemDiplomadosCurso": "Diplomado",
    "PercentagemInscritosMesmoEstabelecimentoCurso": "Inscrito no mesmo curso",
    "PercentagemOutroCursoMesmoEstabelecimento": "Outro curso, mesma escola",
    "PercentagemNoutroEstabelecimento": "Noutra escola",
    "PercentagemNaoEncontradosEnsinoSuperior": "Não encontrado (≈ abandono)",
}
W_SIT = "NumeroInscritosPrimeiroAnoPrimeiraVez2Anos"
ABANDONO = "PercentagemNaoEncontradosEnsinoSuperior"

CONCLUSAO = {
    "PercentagemConclusaoTempoEsperado": "No tempo esperado",
    "PercentagemConclusaoTempoEsperadoMaisUmAno": "Até +1 ano",
    "PercentagemConclusaoTempoEsperadoMaisTresAnos": "Até +3 anos",
}
W_CONC = "NumeroInscritosPrimeiroAnoPrimeiraVez"

PROSSEGUIMENTO = {
    "pct_licenciatura_mesma_ies": "Licenciatura no IPT",
    "pct_licenciatura_outra_ies": "Licenciatura noutra escola",
    "pct_outro_nivel": "Outro nível",
    "pct_nao_encontrados": "Não encontrado no ensino superior",
}

IDADES = {  # coluna InfoCursos -> rótulo
    "Numero1_18Anos": "≤18",
    "Numero19Anos": "19",
    "Numero20Anos": "20",
    "Numero21Anos": "21",
    "Numero22Anos": "22",
    "Numero23Anos": "23",
    "Numero24Anos": "24",
    "Numero25_27Anos": "25–27",
    "Numero28_30Anos": "28–30",
    "Numero31_39Anos": "31–39",
    "Numero40_99Anos": "40+",
}
IDADE_25 = ["Numero25_27Anos", "Numero28_30Anos", "Numero31_39Anos", "Numero40_99Anos"]
PERFIL = {  # indicador -> (rótulo, explicação)
    "pct_mulheres": ("% mulheres", ""),
    "pct_estrangeiros": ("% estrangeiros", "nacionalidade não portuguesa"),
    "pct_25_mais": ("% com 25 ou mais anos", ""),
}

NOTAS = {f"PercentagemNota{k}": k for k in range(10, 21)}
W_NOTA = "NumeroDiplomados2AnosRaides"

# Percurso de uma coorte (ic_Percurso Coorte): em que ano do curso se perdem os alunos.
# Ordem da barra: perdas no 1.º ano -> perdas depois -> neutro -> conclusão (divergente).
SAIU_1, SAIU_2 = "PercentagemSaiuEnsinoSuperior1Ano", "PercentagemSaiuDepois1Ano"
MUDOU_1, CONTINUOU_1 = "PercentagemMudouCurso1Ano", "PercentagemContinuou1Ano"
CONC_N, CONC_N3 = (
    "PercentagemConclusaoTempoEsperado",
    "PercentagemConclusaoTempoEsperadoMaisTresAnos",
)
PERCURSO = {
    SAIU_1: "Saiu no 1.º ano",
    SAIU_2: "Saiu no 2.º ano ou depois",
    MUDOU_1: "Mudou de curso/escola no 1.º ano",
    "concluiu_atraso": "Concluiu com atraso (até +3 anos)",
    CONC_N: "Concluiu no tempo esperado",
}
CORES_PERCURSO = alt.Scale(
    domain=list(PERCURSO.values()),
    range=["#c23b3b", "#f09a92", "#6b717b", "#86b6ef", "#2a78d6"],
)
FUNDO_ESCURO = {SAIU_1, MUDOU_1, CONC_N}  # texto branco por cima destas cores
W_PC = "NumeroNovosInscritos"


# --------------------------------------------------------------------------- dados
@st.cache_data
def load(name: str) -> pd.DataFrame:
    p = DATA / f"{name}.csv"
    return pd.read_csv(p, dtype=TEXT) if p.exists() else pd.DataFrame()


def ponderada(df: pd.DataFrame, by: list[str], cols: list[str], w: str) -> pd.DataFrame:
    """Média de `cols` por grupo, ponderada pelo n.º de alunos `w` (NaN ignorados por coluna)."""
    rows = []
    for key, g in df.groupby(by):
        r = dict(zip(by, key if isinstance(key, tuple) else (key,)))
        r["n_cursos"], r[w] = len(g), g[w].sum()
        for c in cols:
            ok = g[c].notna() & g[w].notna() & (g[w] > 0)
            r[c] = (
                (g.loc[ok, c] * g.loc[ok, w]).sum() / g.loc[ok, w].sum()
                if ok.any()
                else None
            )
        rows.append(r)
    return pd.DataFrame(rows, columns=[*by, "n_cursos", w, *cols])


def filtrar_amostras(df: pd.DataFrame) -> pd.DataFrame:
    if excluir_pequenas and "amostra_pequena" in df:
        return df[~df["amostra_pequena"].astype(bool)]
    return df


def nome_curto(s: pd.Series) -> pd.Series:
    return (
        s.str.replace("Instituto Politécnico", "IP", regex=False)
        .str.replace("Universidade Politécnica", "UP", regex=False)
        .str.replace("Escola Superior de Tecnologia", "ES Tecnologia", regex=False)
        .str.replace("Escola Superior de Gestão", "ES Gestão", regex=False)
        .str.replace("Escola Superior", "ES", regex=False)
    )


@st.cache_data
def perfil_por_curso() -> pd.DataFrame:
    """Uma linha por curso x edição com contagens de sexo, nacionalidade e idade."""
    key = [*CURSO, "Grau", "NomeCurso", "UnidadeOrganica", "AnoLetivo"]
    sexo = load("ic_Inscritos por Sexo")
    nac = load("ic_Inscritos por Nacionalidade")
    ida = load("ic_Inscritos por Idade")
    if sexo.empty or nac.empty or ida.empty:
        return pd.DataFrame()
    p = sexo[
        [*key, "NumeroInscritos", "NumeroHomens", "NumeroMulheres", "amostra_pequena"]
    ]
    p = p.merge(
        nac[[*CURSO, "NumeroPortugueses", "NumeroEstrangeiros"]], on=CURSO, how="outer"
    )
    p = p.merge(
        ida[[*CURSO, "NumeroTotalInscritos", *[c for c in IDADES if c in ida]]],
        on=CURSO,
        how="outer",
    )
    return p


def indicadores_perfil(p: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Somas por grupo -> percentagens (cada uma sobre o seu próprio total)."""
    s = p.groupby(by, as_index=False)[
        [
            "NumeroInscritos",
            "NumeroMulheres",
            "NumeroHomens",
            "NumeroPortugueses",
            "NumeroEstrangeiros",
            "NumeroTotalInscritos",
            *IDADES,
        ]
    ].sum(min_count=1)
    s["pct_mulheres"] = (
        100 * s["NumeroMulheres"] / (s["NumeroMulheres"] + s["NumeroHomens"])
    )
    s["pct_estrangeiros"] = (
        100
        * s["NumeroEstrangeiros"]
        / (s["NumeroEstrangeiros"] + s["NumeroPortugueses"])
    )
    s["pct_25_mais"] = 100 * s[IDADE_25].sum(axis=1) / s[list(IDADES)].sum(axis=1)
    return s


# --------------------------------------------------------------------------- gráficos
def ranking(
    cmp: pd.DataFrame,
    grau: str,
    col: str,
    titulo: str,
    fmt: str = ".1f",
    quando: str | None = None,
) -> None:
    """Barras horizontais, uma por politécnico público; a instituição a verde.
    `quando` substitui "edição N" na legenda (p. ex. as coortes seguidas)."""
    d = cmp[(cmp["Grau"] == grau)].dropna(subset=[col]).copy()
    if d.empty:
        st.info("Sem dados de comparação.")
        return
    d["nome"] = nome_curto(d["Estabelecimento"])
    d = d.sort_values(col, ascending=False).reset_index(drop=True)
    w = next(c for c in d.columns if c.startswith("Numero"))
    chart = (
        alt.Chart(d)
        .mark_bar()
        .encode(
            x=alt.X(f"{col}:Q", title=titulo, scale=alt.Scale(zero=fmt == ".1f")),
            y=alt.Y("nome:N", sort=None, title=None),
            color=alt.condition(
                alt.datum.eh_instituicao, alt.value(COR_IPT), alt.value(COR_OUTROS)
            ),
            tooltip=[
                "Estabelecimento",
                alt.Tooltip(f"{col}:Q", format=fmt, title=titulo),
                alt.Tooltip("n_cursos:Q", title="cursos"),
                alt.Tooltip(f"{w}:Q", title="alunos"),
            ],
        )
        .properties(height=max(22 * len(d), 120))
    )
    st.altair_chart(chart, width="stretch")
    pos = d.index[d["eh_instituicao"].astype(bool)]
    if len(pos):
        st.caption(
            f"Tomar: {pos[0] + 1}.º valor mais alto em {len(d)} politécnicos públicos "
            f"({quando or 'edição ' + str(int(d['edicao'].iat[0]))})."
        )


def barras_empilhadas(df: pd.DataFrame, y: str, mapa: dict, titulo_y=None) -> alt.Chart:
    """df largo (uma linha por categoria y) -> barras 100% empilhadas."""
    long = df.melt(
        id_vars=[y],
        value_vars=[c for c in mapa if c in df],
        var_name="indicador",
        value_name="pct",
    )
    long["ordem"] = long["indicador"].map({k: i for i, k in enumerate(mapa)})
    long["indicador"] = long["indicador"].map(mapa)
    return (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("pct:Q", title="% dos alunos", stack="zero"),
            y=alt.Y(f"{y}:N", title=titulo_y, sort=None),
            color=alt.Color(
                "indicador:N",
                sort=list(mapa.values()),
                title=None,
                legend=alt.Legend(orient="bottom", columns=3),
            ),
            order="ordem:Q",
            tooltip=[y, "indicador", alt.Tooltip("pct:Q", format=".1f", title="%")],
        )
    )


def percurso_agregado(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Médias ponderadas do percurso + as partes que a barra precisa."""
    a = ponderada(df, by, [SAIU_1, MUDOU_1, CONTINUOU_1, SAIU_2, CONC_N, CONC_N3], W_PC)
    a["concluiu_atraso"] = a[CONC_N3] - a[CONC_N]
    # dos que ainda estavam no curso 1 ano depois, quantos não concluíram
    a["nao_conclui_apos_1"] = 100 * a[SAIU_2] / a[CONTINUOU_1]
    return a


def barras_percurso(df: pd.DataFrame, y: str) -> alt.LayerChart:
    """Uma barra por linha de df: o que aconteceu a 100 alunos que entraram, com o % escrito
    nos segmentos com espaço para isso."""
    long = df.melt(
        id_vars=[y, W_PC], value_vars=list(PERCURSO), var_name="k", value_name="pct"
    )
    long["pct"] = long["pct"].fillna(0)
    long["resultado"] = long["k"].map(PERCURSO)
    long["ordem"] = long["k"].map({k: i for i, k in enumerate(PERCURSO)})
    long = long.sort_values([y, "ordem"])
    long["fim"] = long.groupby(y)["pct"].cumsum()
    long["inicio"] = long["fim"] - long["pct"]
    long["meio"] = (long["inicio"] + long["fim"]) / 2
    long["escuro"] = long["k"].isin(FUNDO_ESCURO)
    base = alt.Chart(long).encode(
        y=alt.Y(f"{y}:N", sort=list(df[y]), title=None, axis=alt.Axis(labelLimit=340))
    )
    barras = base.mark_bar().encode(
        x=alt.X(
            "inicio:Q",
            title="% dos alunos que entraram no 1.º ano",
            scale=alt.Scale(domain=[0, 100], nice=False, clamp=True),
        ),
        x2="fim:Q",
        color=alt.Color(
            "resultado:N",
            scale=CORES_PERCURSO,
            sort=list(PERCURSO.values()),
            title=None,
            legend=alt.Legend(orient="bottom", columns=3),
        ),
        tooltip=[
            alt.Tooltip(f"{y}:N", title="grupo"),
            "resultado",
            alt.Tooltip("pct:Q", format=".1f", title="%"),
            alt.Tooltip(f"{W_PC}:Q", title="alunos que entraram"),
        ],
    )
    texto = (
        base.transform_filter(alt.datum.pct >= 6)
        .mark_text(fontSize=11)
        .encode(
            x="meio:Q",
            text=alt.Text("pct:Q", format=".0f"),
            color=alt.condition(
                alt.datum.escuro, alt.value("#ffffff"), alt.value("#0b0b0b")
            ),
        )
    )
    return barras + texto


def linhas(
    df: pd.DataFrame,
    x: str,
    y: str,
    cor: str,
    titulo_y: str,
    extra=(),
    escala=None,
    zero=True,
) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X(f"{x}:O", title=None),
            y=alt.Y(f"{y}:Q", title=titulo_y, scale=alt.Scale(zero=zero)),
            color=alt.Color(f"{cor}:N", title=None, scale=escala or alt.Undefined),
            tooltip=[x, cor, alt.Tooltip(f"{y}:Q", format=".1f"), *extra],
        )
    )


# --------------------------------------------------------------------------- página
st.set_page_config(page_title="CTeSP no IPT", layout="wide")
st.title("CTeSP no Politécnico de Tomar")

if not DATA.exists() or load("ic_Situacao Apos 1 Ano").empty:
    st.error("Falta data/processed/. Corre primeiro `uv run python -m pipeline`.")
    st.stop()

with st.sidebar:
    st.header("Opções")
    excluir_pequenas = st.checkbox(
        f"Excluir cursos com amostra pequena (n ≤ {MAX_N_PEQUENA})",
        value=False,
        help="Afeta só os dados por curso do IPT. As comparações entre escolas já vêm "
        "agregadas do pipeline e incluem todos os cursos.",
    )
    st.caption(
        "Fontes: InfoCursos (DGEEC) e relatórios de prosseguimento de estudos da DGEEC. "
        "Ver o separador *Dados e método*."
    )

sit = filtrar_amostras(load("ic_Situacao Apos 1 Ano"))
sit_cmp = load("ic_cmp_Situacao Apos 1 Ano")
sit_cols = [c for c in SITUACAO if c in sit]
ed_max = int(sit["edicao"].max())
serie = ponderada(sit, ["edicao", "Grau"], [ABANDONO], W_SIT)
serie["coortes"] = serie["edicao"].map(
    sit.groupby("edicao")["AnosInscritosPrimeiroAnoPrimeiraVez"].first()
)
perfil = perfil_por_curso()
if not perfil.empty:
    perfil = filtrar_amostras(perfil)

# percurso: a coorte mais recente que já se consegue seguir até ao fim, por grau
perc = load("ic_Percurso Coorte")
if not perc.empty:
    perc = perc[perc["edicao"] == perc.groupby("Grau")["edicao"].transform("max")]
    coorte_ipt = filtrar_amostras(perc[perc["eh_instituicao"].astype(bool)])
    coorte_ipt_g = percurso_agregado(coorte_ipt, ["Grau"])
    coorte_ipt_g["grupo"] = "IPT · " + coorte_ipt_g["Grau"]
    coorte_par_g = percurso_agregado(perc, ["Grau"])
    coorte_par_g["grupo"] = "Politécnicos públicos · " + coorte_par_g["Grau"]
    coortes_seguidas = perc.groupby("Grau")["coortes"].agg(lambda s: s.mode().iat[0])

tabs = st.tabs(
    [
        "1. Quem entra",
        "2. Procura",
        "3. Abandono",
        "4. CTeSP vs Licenciatura",
        "5. Prosseguimento",
        "6. Notas finais",
        "Dados e método",
    ]
)

# ---------------------------------------------------------------- 1. perfil
with tabs[0]:
    st.subheader("Quem são os alunos de CTeSP?")
    st.caption(
        "Todos os inscritos no IPT (todos os anos do curso), por ano letivo. "
        "CTeSP disponível a partir de 2017/18. Sem comparação com outras escolas: "
        "o pipeline só extrai estas folhas para o IPT."
    )
    if perfil.empty:
        st.info("Sem dados de perfil.")
    else:
        por_ano = indicadores_perfil(perfil, ["AnoLetivo", "Grau"])
        ano_max = por_ano.loc[por_ano["Grau"] == "CTeSP", "AnoLetivo"].max()
        agora = por_ano[por_ano["AnoLetivo"] == ano_max].set_index("Grau")

        cols = st.columns(len(PERFIL))
        for col, (k, (rot, _)) in zip(cols, PERFIL.items()):
            if {"CTeSP", "Licenciatura"} <= set(agora.index):
                c, l = agora.at["CTeSP", k], agora.at["Licenciatura", k]
                col.metric(
                    f"{rot} · CTeSP ({ano_max})",
                    f"{c:.1f} %",
                    delta=f"{c - l:+.1f} pp vs licenciatura",
                    delta_color="off",
                )

        st.markdown(f"#### Idade dos inscritos ({ano_max})")
        ida = agora.reset_index().melt(
            id_vars=["Grau"], value_vars=list(IDADES), var_name="idade", value_name="n"
        )
        ida["pct"] = 100 * ida["n"] / ida.groupby("Grau")["n"].transform("sum")
        ida["idade"] = ida["idade"].map(IDADES)
        st.altair_chart(
            alt.Chart(ida)
            .mark_bar()
            .encode(
                x=alt.X(
                    "idade:N",
                    sort=list(IDADES.values()),
                    title="Idade",
                    axis=alt.Axis(labelAngle=0),
                ),
                xOffset="Grau:N",
                y=alt.Y("pct:Q", title="% dos inscritos"),
                color=alt.Color("Grau:N", scale=CORES_GRAU, title=None),
                tooltip=["Grau", "idade", alt.Tooltip("pct:Q", format=".1f"), "n"],
            )
            .properties(height=280),
            width="stretch",
        )
        st.caption(
            "Os escalões 25–27, 28–30, 31–39 e 40+ juntam vários anos de idade; "
            "compare as barras entre graus, não a altura entre escalões."
        )

        st.markdown("#### Evolução")
        ind = st.selectbox(
            "Indicador",
            list(PERFIL),
            format_func=lambda k: PERFIL[k][0],
            key="ind_perfil",
        )
        st.altair_chart(
            linhas(
                por_ano,
                "AnoLetivo",
                ind,
                "Grau",
                PERFIL[ind][0],
                extra=["NumeroInscritos"],
                escala=CORES_GRAU,
            ),
            width="stretch",
        )

        st.markdown(f"#### Por curso (CTeSP, {ano_max})")
        pc = indicadores_perfil(
            perfil[(perfil["AnoLetivo"] == ano_max) & (perfil["Grau"] == "CTeSP")],
            ["NomeCurso", "UnidadeOrganica"],
        )
        pc = (
            pc[["NomeCurso", "UnidadeOrganica", "NumeroInscritos", *PERFIL]]
            .rename(
                columns={
                    "NumeroInscritos": "inscritos",
                    **{k: v[0] for k, v in PERFIL.items()},
                }
            )
            .sort_values("inscritos", ascending=False)
        )
        st.dataframe(
            pc,
            hide_index=True,
            width="stretch",
            column_config={
                v[0]: st.column_config.NumberColumn(format="%.0f %%")
                for v in PERFIL.values()
            },
        )

# ---------------------------------------------------------------- 2. procura
with tabs[1]:
    st.subheader("O CTeSP está a crescer ou a encolher no IPT?")
    st.caption(
        "N.º de inscritos (todos os anos do curso) por ano letivo, InfoCursos. "
        "Mede a procura efetiva; não é o n.º de vagas, que nenhuma das fontes publica."
    )
    ins = filtrar_amostras(load("ic_Numero Inscritos"))
    if ins.empty:
        st.info("Sem dados de inscritos.")
    else:
        ins = ins[ins["Grau"] == "CTeSP"].copy()
        ins = ins[ins["NumeroInscritos"] > 0]
        anos = sorted(ins["ano"].unique())
        tot = ins.groupby("ano", as_index=False).agg(
            inscritos=("NumeroInscritos", "sum"), cursos=("CodigoCurso", "nunique")
        )
        base = tot[tot["cursos"] >= 5].iloc[
            0
        ]  # 1.º ano “completo” (2014/15 só tem 1 curso)
        ult, pico = tot.iloc[-1], tot.loc[tot["inscritos"].idxmax()]

        c1, c2, c3 = st.columns(3)
        c1.metric(
            f"Inscritos CTeSP ({ult['ano']})",
            f"{ult['inscritos']:.0f}",
            delta=f"{100 * (ult['inscritos'] / base['inscritos'] - 1):+.0f} % desde {base['ano']}",
        )
        c2.metric(f"Máximo ({pico['ano']})", f"{pico['inscritos']:.0f}")
        c3.metric(
            f"Cursos ativos ({ult['ano']})",
            f"{ult['cursos']:.0f}",
            delta=f"{ult['cursos'] - base['cursos']:+.0f} desde {base['ano']}",
            delta_color="off",
        )

        ins["escola"] = nome_curto(ins["UnidadeOrganica"])
        st.altair_chart(
            alt.Chart(ins)
            .mark_bar()
            .encode(
                x=alt.X("ano:O", title=None),
                y=alt.Y("sum(NumeroInscritos):Q", title="Inscritos CTeSP"),
                color=alt.Color(
                    "escola:N", title=None, legend=alt.Legend(orient="bottom")
                ),
                tooltip=[
                    "ano",
                    "escola",
                    alt.Tooltip("sum(NumeroInscritos):Q", title="inscritos"),
                    alt.Tooltip("distinct(CodigoCurso):Q", title="cursos"),
                ],
            )
            .properties(height=320),
            width="stretch",
        )

        st.markdown("#### Por curso")
        rows = []
        for (codigo, nome, escola), g in ins.groupby(
            ["CodigoCurso", "NomeCurso", "escola"]
        ):
            g = g.set_index("ano")["NumeroInscritos"]
            primeiro, ultimo = g.index.min(), g.index.max()
            estado = (
                "fechado (último ano " + ultimo + ")"
                if ultimo < anos[-1]
                else "novo (desde " + primeiro + ")"
                if primeiro >= anos[-3]
                else "ativo"
            )
            rows.append(
                {
                    "curso": nome,
                    "escola": escola,
                    "estado": estado,
                    "evolução": [float(g.get(a, 0)) for a in anos],
                    f"inscritos {anos[-1]}": g.get(anos[-1]),
                    "pico": g.max(),
                    "1.º ano": primeiro,
                }
            )
        tab = pd.DataFrame(rows).sort_values(
            ["estado", f"inscritos {anos[-1]}"], ascending=[True, False]
        )
        st.dataframe(
            tab,
            hide_index=True,
            width="stretch",
            column_config={
                "evolução": st.column_config.LineChartColumn(
                    f"evolução {anos[0]}–{anos[-1]}", y_min=0
                )
            },
        )
        st.caption(
            "“Novo” = surgiu nos últimos 3 anos. “Fechado” = sem inscritos no ano mais recente. "
            "Um curso pode mudar de código ao ser reestruturado e aparecer como fechado + novo."
        )

# ---------------------------------------------------------------- 3. abandono
with tabs[2]:
    st.subheader("Quantos alunos de CTeSP abandonam?")
    st.caption(
        "Alunos inscritos pela 1.ª vez no 1.º ano (2 coortes por edição), 1 ano depois. "
        "“Não encontrado no ensino superior” é a melhor aproximação ao abandono, "
        "mas inclui quem foi estudar para o estrangeiro ou interrompeu e voltou mais tarde."
    )

    ipt_now = ponderada(sit[sit["edicao"] == ed_max], ["Grau"], sit_cols, W_SIT)
    ipt_now["grupo"] = "IPT · " + ipt_now["Grau"]
    pares = ponderada(sit_cmp, ["Grau"], sit_cols, W_SIT)
    pares["grupo"] = "Politécnicos públicos · " + pares["Grau"]
    comp = pd.concat([ipt_now, pares]).sort_values(
        ["Grau", "grupo"], ascending=[True, False]
    )

    def valor(df, g, col=ABANDONO):
        return (
            df.loc[df["Grau"] == g, col].squeeze() if (df["Grau"] == g).any() else None
        )

    c1, c2, c3 = st.columns(3)
    a_ipt, a_pares, a_lic = (
        valor(ipt_now, "CTeSP"),
        valor(pares, "CTeSP"),
        valor(ipt_now, "Licenciatura"),
    )
    if a_ipt is not None:
        c1.metric(
            "Abandono CTeSP · IPT",
            f"{a_ipt:.1f} %",
            delta=f"{a_ipt - a_pares:+.1f} pp vs politécnicos"
            if a_pares is not None
            else None,
            delta_color="inverse",
        )
    if a_pares is not None:
        c2.metric("Abandono CTeSP · politécnicos públicos", f"{a_pares:.1f} %")
    if a_lic is not None:
        c3.metric("Abandono Licenciatura · IPT", f"{a_lic:.1f} %")

    st.altair_chart(
        barras_empilhadas(comp, "grupo", SITUACAO).properties(height=200),
        width="stretch",
    )
    st.caption(
        f"Edição InfoCursos {ed_max}. Médias ponderadas pelo n.º de alunos de cada curso."
    )

    st.markdown("#### Comparação com as outras escolas (CTeSP)")
    ranking(sit_cmp, "CTeSP", ABANDONO, "% não encontrados no ensino superior")

    st.markdown("#### Evolução no IPT")
    st.altair_chart(
        linhas(
            serie,
            "edicao",
            ABANDONO,
            "Grau",
            "% não encontrados",
            extra=["coortes", "n_cursos"],
            escala=CORES_GRAU,
        ),
        width="stretch",
    )
    st.caption("O CTeSP só aparece na InfoCursos a partir da edição 2019.")

    # ---- em que ano do curso saem
    st.markdown("### Saem no 1.º ou no 2.º ano?")
    if perc.empty or not (coorte_ipt_g["Grau"] == "CTeSP").any():
        st.info("Sem dados para seguir uma coorte de CTeSP até ao fim do curso.")
    else:
        c_ipt = coorte_ipt_g.set_index("Grau").loc["CTeSP"]
        c_par = coorte_par_g.set_index("Grau").loc["CTeSP"]
        st.caption(
            f"Os mesmos alunos seguidos do 1.º ano até ao diploma: entraram no CTeSP em "
            f"{coortes_seguidas['CTeSP']}. Junta, curso a curso, a situação 1 ano após entrar com a "
            "taxa de conclusão. “2.º ano ou depois” = ainda estava no curso 1 ano depois de "
            "entrar, mas não o concluiu até 3 anos após o tempo esperado (5 anos depois de entrar)."
        )
        c1, c2, c3 = st.columns(3)
        for col, k, rot in (
            (c1, SAIU_1, "Saem no 1.º ano · IPT"),
            (c2, SAIU_2, "Saem no 2.º ano ou depois · IPT"),
            (c3, "nao_conclui_apos_1", "Dos que passam o 1.º ano, não concluem"),
        ):
            col.metric(
                rot,
                f"{c_ipt[k]:.1f} %",
                delta=f"{c_ipt[k] - c_par[k]:+.1f} pp vs politécnicos",
                delta_color="inverse",
            )
        st.altair_chart(
            barras_percurso(
                pd.concat([coorte_ipt_g, coorte_par_g]).query("Grau == 'CTeSP'"), "grupo"
            ).properties(height=130),
            width="stretch",
        )
        d1, d2 = c_ipt[SAIU_1] - c_par[SAIU_1], c_ipt[SAIU_2] - c_par[SAIU_2]
        st.markdown(
            f"Por cada **100 alunos** que entram num CTeSP do IPT, **{c_ipt[SAIU_1]:.0f}** saem do "
            f"ensino superior logo no 1.º ano e **{c_ipt[MUDOU_1]:.0f}** mudam de curso ou de escola; "
            f"outros **{c_ipt[SAIU_2]:.0f}** passam o 1.º ano mas não chegam a concluir. "
            f"Face aos politécnicos públicos, a diferença está sobretudo "
            f"**{'no 1.º ano' if d1 > d2 else 'no 2.º ano ou depois'}** "
            f"({d1:+.1f} pp no 1.º ano, {d2:+.1f} pp depois)."
        )
        ed_coorte = int(perc.loc[perc["Grau"] == "CTeSP", "edicao"].iat[0])
        todos = sit[(sit["edicao"] == ed_coorte) & (sit["Grau"] == "CTeSP")]
        st.caption(
            f"IPT: {int(c_ipt['n_cursos'])} de {len(todos)} cursos e {c_ipt[W_PC]:.0f} de "
            f"{todos[W_SIT].sum():.0f} alunos; os outros cursos não têm taxa de conclusão "
            f"publicada para todas as suas coortes. Politécnicos públicos: {int(c_par['n_cursos'])} "
            f"cursos, {c_par[W_PC]:.0f} alunos (inclui o IPT). Médias ponderadas pelo n.º de alunos. "
            "“Saiu no 2.º ano ou depois” inclui também quem mudou de curso mais tarde e os poucos "
            "que ainda estão inscritos 5 anos depois."
        )

        st.markdown("#### Comparação com as outras escolas (CTeSP)")
        coorte_inst = percurso_agregado(perc, ["Estabelecimento", "Grau"])
        coorte_inst["eh_instituicao"] = coorte_inst["Estabelecimento"].isin(
            perc.loc[perc["eh_instituicao"].astype(bool), "Estabelecimento"]
        )
        quando = f"entradas {coortes_seguidas['CTeSP']}"
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Saem no 1.º ano**")
            ranking(coorte_inst, "CTeSP", SAIU_1, "% saiu no 1.º ano", quando=quando)
        with c2:
            st.markdown("**Saem no 2.º ano ou depois**")
            ranking(coorte_inst, "CTeSP", SAIU_2, "% saiu no 2.º ano ou depois", quando=quando)

        st.markdown("#### Por curso (IPT, CTeSP)")
        coorte_cursos = coorte_ipt[coorte_ipt["Grau"] == "CTeSP"].copy()
        coorte_cursos["concluiu_atraso"] = coorte_cursos[CONC_N3] - coorte_cursos[CONC_N]
        coorte_cursos["curso"] = coorte_cursos["NomeCurso"]
        dup = coorte_cursos["curso"].duplicated(keep=False)
        coorte_cursos.loc[dup, "curso"] += " · " + nome_curto(coorte_cursos.loc[dup, "UnidadeOrganica"])
        coorte_cursos["curso"] += " (n=" + coorte_cursos[W_PC].astype(int).astype(str) + ")"
        coorte_cursos = coorte_cursos.assign(perda=coorte_cursos[SAIU_1] + coorte_cursos[SAIU_2]).sort_values(
            "perda", ascending=False
        )
        st.altair_chart(
            barras_percurso(coorte_cursos, "curso").properties(height=30 * len(coorte_cursos) + 60),
            width="stretch",
        )
        st.caption(
            "Ordenado pelo total que saiu sem concluir (1.º ano + depois). "
            "Em cursos com poucos alunos, um aluno muda o valor vários pontos percentuais."
        )

    # ---- por curso e escola
    st.markdown("### O abandono depende do curso ou da escola?")
    eds = sorted(sit.loc[sit["Grau"] == "CTeSP", "edicao"].unique(), reverse=True)
    ed = st.selectbox(
        "Edição InfoCursos",
        eds,
        key="ed_curso",
        help="Edições seguidas partilham uma coorte, por isso não se somam.",
    )
    cur = sit[(sit["edicao"] == ed) & (sit["Grau"] == "CTeSP")].copy()
    cur["escola"] = nome_curto(cur["UnidadeOrganica"])

    esc = ponderada(cur, ["escola"], [ABANDONO], W_SIT)
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Por escola**")
        st.altair_chart(
            alt.Chart(esc)
            .mark_bar(color=COR_IPT)
            .encode(
                x=alt.X(f"{ABANDONO}:Q", title="% não encontrados"),
                y=alt.Y("escola:N", sort="-x", title=None),
                tooltip=[
                    "escola",
                    alt.Tooltip(f"{ABANDONO}:Q", format=".1f"),
                    "n_cursos",
                    alt.Tooltip(f"{W_SIT}:Q", title="alunos"),
                ],
            )
            .properties(height=150),
            width="stretch",
        )
        st.dataframe(
            esc.rename(columns={W_SIT: "alunos", ABANDONO: "% abandono"}),
            hide_index=True,
            width="stretch",
            column_config={
                "% abandono": st.column_config.NumberColumn(format="%.1f %%")
            },
        )

    with c2:
        st.markdown("**Por curso: o que anda junto com o abandono?**")
        if not perfil.empty:
            pc = indicadores_perfil(perfil[perfil["edicao"] == ed], CURSO)
            cur = cur.merge(pc[[*CURSO, *PERFIL]], on=CURSO, how="left")
        eixos = {
            W_SIT: "N.º de alunos (2 coortes)",
            **{k: v[0] for k, v in PERFIL.items() if k in cur},
        }
        x = st.selectbox(
            "Eixo horizontal", list(eixos), format_func=eixos.get, key="eixo_x"
        )
        d = cur.dropna(subset=[x, ABANDONO])
        st.altair_chart(
            alt.Chart(d)
            .mark_circle(opacity=0.8)
            .encode(
                x=alt.X(f"{x}:Q", title=eixos[x]),
                y=alt.Y(f"{ABANDONO}:Q", title="% não encontrados"),
                size=alt.Size(f"{W_SIT}:Q", title="alunos", legend=None),
                color=alt.Color(
                    "escola:N", title=None, legend=alt.Legend(orient="bottom")
                ),
                tooltip=[
                    "NomeCurso",
                    "escola",
                    alt.Tooltip(f"{ABANDONO}:Q", format=".1f"),
                    alt.Tooltip(f"{x}:Q", format=".1f", title=eixos[x]),
                    alt.Tooltip(f"{W_SIT}:Q", title="alunos"),
                ],
            )
            .properties(height=320),
            width="stretch",
        )
        if len(d) >= 5:
            r = d[x].rank().corr(d[ABANDONO].rank())  # Spearman = Pearson das ordens
            forca = "fraca" if abs(r) < 0.3 else "moderada" if abs(r) < 0.6 else "forte"
            st.caption(
                f"Correlação de Spearman = {r:+.2f} ({forca}, {len(d)} cursos). "
                "É uma associação entre cursos, não prova causa nem se aplica a cada aluno. "
                "O perfil é de todos os inscritos, o abandono é só dos que entraram."
            )

    st.markdown(f"#### Tabela por curso (CTeSP, edição {ed})")
    tab = (
        cur[["NomeCurso", "escola", W_SIT, *sit_cols, "amostra_pequena"]]
        .rename(columns={W_SIT: "n alunos", **SITUACAO})
        .sort_values(SITUACAO[ABANDONO], ascending=False)
    )
    st.dataframe(
        tab,
        hide_index=True,
        width="stretch",
        column_config={
            v: st.column_config.NumberColumn(format="%.1f %%")
            for v in SITUACAO.values()
        },
    )

# ---------------------------------------------------------------- 4. CTeSP vs Lic
with tabs[3]:
    st.subheader("CTeSP vs Licenciatura no IPT")
    st.caption(
        "Atenção: o CTeSP dura 2 anos e a licenciatura 3. “No tempo esperado” respeita a duração de cada um."
    )

    st.markdown("#### Abandono (1 ano após entrar)")
    st.altair_chart(
        linhas(
            serie,
            "edicao",
            ABANDONO,
            "Grau",
            "% não encontrados",
            extra=["coortes"],
            escala=CORES_GRAU,
        ),
        width="stretch",
    )

    st.markdown("#### Conclusão")
    tc = filtrar_amostras(load("ic_Taxa de Conclusao"))
    tc_cmp = load("ic_cmp_Taxa de Conclusao")
    conc_cols = [c for c in CONCLUSAO if c in tc]
    if tc.empty:
        st.info("Sem dados de conclusão.")
    else:
        ed_tc = int(tc["edicao"].max())
        ipt_c = ponderada(tc[tc["edicao"] == ed_tc], ["Grau"], conc_cols, W_CONC)
        par_c = ponderada(tc_cmp, ["Grau"], conc_cols, W_CONC)
        ipt_c["grupo"], par_c["grupo"] = "IPT", "Politécnicos públicos"
        both = pd.concat([ipt_c, par_c]).melt(
            id_vars=["Grau", "grupo"],
            value_vars=conc_cols,
            var_name="medida",
            value_name="pct",
        )
        both["medida"] = both["medida"].map(CONCLUSAO)
        st.altair_chart(
            alt.Chart(both)
            .mark_bar()
            .encode(
                x=alt.X(
                    "medida:N",
                    sort=list(CONCLUSAO.values()),
                    title=None,
                    axis=alt.Axis(labelAngle=0),
                ),
                xOffset=alt.XOffset("grupo:N"),
                y=alt.Y("pct:Q", title="% que concluiu"),
                color=alt.Color(
                    "grupo:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["IPT", "Politécnicos públicos"],
                        range=[COR_IPT, COR_OUTROS],
                    ),
                ),
                column=alt.Column("Grau:N", title=None),
                tooltip=["Grau", "grupo", "medida", alt.Tooltip("pct:Q", format=".1f")],
            )
            .properties(width=260, height=260)
        )
        coorte = (
            tc[tc["edicao"] == ed_tc]
            .dropna(subset=["AnoInscritosPrimeiroAnoPrimeiraVez"])
            .groupby("Grau")["AnoInscritosPrimeiroAnoPrimeiraVez"]
            .first()
        )
        st.caption(
            f"Edição {ed_tc}; alunos que entraram em "
            + "; ".join(f"{a} ({g})" for g, a in coorte.items())
            + ". Cada grau segue uma coorte diferente."
        )

        grau = st.radio(
            "Comparar escolas em:",
            ["CTeSP", "Licenciatura"],
            horizontal=True,
            key="g_conc",
        )
        ranking(
            tc_cmp,
            grau,
            "PercentagemConclusaoTempoEsperado",
            "% concluiu no tempo esperado",
        )

    st.markdown("#### Em que ano do curso se perdem alunos?")
    if perc.empty:
        st.info("Sem dados para seguir uma coorte até ao fim do curso.")
    else:
        grupos = pd.concat([coorte_ipt_g, coorte_par_g]).sort_values(
            ["Grau", "grupo"]  # IPT antes dos politécnicos, como no separador 3
        )
        st.altair_chart(
            barras_percurso(grupos, "grupo").properties(height=60 * len(grupos)),
            width="stretch",
        )
        g_ipt = coorte_ipt_g.set_index("Grau")
        if {"CTeSP", "Licenciatura"} <= set(g_ipt.index):
            artigo = {"CTeSP": "o CTeSP", "Licenciatura": "a licenciatura"}
            frase = [
                f"{artigo[g]} perde mais alunos "
                f"**{'no 1.º ano' if r[SAIU_1] > r[SAIU_2] else 'no 2.º ano ou depois'}** "
                f"({r[SAIU_1]:.0f} contra {r[SAIU_2]:.0f} em cada 100 que entram)"
                for g, r in g_ipt.loc[["CTeSP", "Licenciatura"]].iterrows()
            ]
            st.markdown("No IPT, " + "; ".join(frase) + ".")
        dur_lic = set(
            pd.to_numeric(
                perc.loc[perc["Grau"] == "Licenciatura", "DuracaoCurso"], errors="coerce"
            ).dropna()
        )
        st.caption(
            "Os mesmos alunos seguidos da entrada ao diploma (situação 1 ano após entrar + "
            "taxa de conclusão, curso a curso). Entradas: "
            + "; ".join(f"{g} {c}" for g, c in coortes_seguidas.items())
            + ". "
            + (
                "Só licenciaturas de 3 anos: as de 4 anos seguem outra coorte. "
                if dur_lic == {3}
                else ""
            )
            + "Na licenciatura, “2.º ano ou depois” cobre dois anos do curso (2.º e 3.º); "
            "no CTeSP, só o 2.º."
        )

# ---------------------------------------------------------------- 5. prosseguimento
with tabs[4]:
    st.subheader("Os diplomados CTeSP seguem para licenciatura?")
    st.caption(
        "Situação no ano letivo seguinte ao diploma (relatórios DGEEC). "
        "Mede-se 1 ano após *concluir*, não após entrar."
    )
    dg = load("dg_ctesp_ipt")
    nac = load("dg_ctesp_nacional")
    if dg.empty:
        st.info("Sem dados DGEEC para o CTeSP.")
    else:
        dg = dg.dropna(subset=["ano_letivo_diploma"]).sort_values("ano_letivo_diploma")
        dg["pct_licenciatura"] = (
            dg["pct_licenciatura_mesma_ies"] + dg["pct_licenciatura_outra_ies"]
        )
        grandes = dg[~dg["amostra_pequena"].astype(bool)]
        ult = (grandes if len(grandes) else dg).iloc[-1]
        fica = (
            100 * ult["pct_licenciatura_mesma_ies"] / ult["pct_licenciatura"]
            if ult["pct_licenciatura"]
            else None
        )

        c1, c2, c3 = st.columns(3)
        c1.metric(
            f"Seguem para licenciatura ({ult['ano_letivo_diploma']})",
            f"{ult['pct_licenciatura']:.0f} %",
        )
        if fica is not None:
            c2.metric("Desses, ficam no IPT", f"{fica:.0f} %")
        c3.metric("Diplomados CTeSP nesse ano", f"{int(ult['n_diplomados'])}")

        dg["ano"] = (
            dg["ano_letivo_diploma"]
            + " (n="
            + dg["n_diplomados"].astype(int).astype(str)
            + ")"
        )
        st.altair_chart(
            barras_empilhadas(dg, "ano", PROSSEGUIMENTO, "Ano do diploma").properties(
                height=40 * len(dg) + 40
            ),
            width="stretch",
        )

        st.markdown("#### IPT vs nacional: % que segue para licenciatura")
        a = dg[["ano_letivo_diploma", "pct_licenciatura"]].assign(grupo="IPT")
        if not nac.empty:
            n = nac.assign(
                pct_licenciatura=nac["pct_licenciatura"]
                + nac.get("pct_mestrado_integrado", 0)
            )
            a = pd.concat(
                [
                    a,
                    n[["ano_letivo_diploma", "pct_licenciatura"]].assign(
                        grupo="Nacional"
                    ),
                ]
            )
        st.altair_chart(
            linhas(a, "ano_letivo_diploma", "pct_licenciatura", "grupo", "%"),
            width="stretch",
        )

        if dg["amostra_pequena"].astype(bool).any():
            st.warning(
                f"Anos com {MAX_N_PEQUENA} ou menos diplomados (pouco fiáveis): "
                + ", ".join(
                    dg.loc[dg["amostra_pequena"].astype(bool), "ano_letivo_diploma"]
                )
            )
        if dg["relatorios_discordam"].astype(bool).any():
            st.warning(
                "Há anos em que relatórios diferentes dão valores diferentes (usa-se o mais recente)."
            )
        st.info(
            "**Porquê mudar de escola?** Os dados mostram *quantos* vão para outra escola, "
            "mas não *porquê*. Explicar isso (oferta de cursos, condições, localização) "
            "exigiria outra fonte, por exemplo um inquérito."
        )

# ---------------------------------------------------------------- 6. notas
with tabs[5]:
    st.subheader("Com que nota saem os diplomados?")
    st.caption(
        "Classificação final dos diplomados (2 anos de diplomados por edição), InfoCursos. "
        "Notas mais altas não significam necessariamente mais aprendizagem: "
        "os critérios de avaliação diferem entre cursos, graus e escolas."
    )
    cf = filtrar_amostras(load("ic_Classificacoes Finais"))
    cf_cmp = load("ic_cmp_Classificacoes Finais")
    if cf.empty:
        st.info("Sem dados de classificações.")
    else:
        nota_cols = [c for c in NOTAS if c in cf]
        ed_cf = int(cf["edicao"].max())

        def nota_media(df: pd.DataFrame) -> pd.Series:
            """Média a partir da distribuição (% por nota 10..20)."""
            pct = df[nota_cols]
            return (pct * [NOTAS[c] for c in nota_cols]).sum(axis=1) / pct.sum(axis=1)

        ipt_n = ponderada(cf[cf["edicao"] == ed_cf], ["Grau"], nota_cols, W_NOTA)
        par_n = ponderada(cf_cmp, ["Grau"], nota_cols, W_NOTA)
        for df, g in ((ipt_n, "IPT"), (par_n, "Politécnicos públicos")):
            df["grupo"], df["nota_media"] = g, nota_media(df)
        cf_cmp = cf_cmp.assign(nota_media=nota_media(cf_cmp))

        c = st.columns(4)
        for i, (df, g) in enumerate(((ipt_n, "IPT"), (par_n, "politécnicos"))):
            for j, grau in enumerate(("CTeSP", "Licenciatura")):
                v = valor(df, grau, "nota_media")
                if v is not None:
                    c[2 * j + i].metric(f"Nota média {grau} · {g}", f"{v:.2f}")

        st.markdown(f"#### Distribuição das notas (edição {ed_cf})")
        dist = pd.concat([ipt_n, par_n]).melt(
            id_vars=["Grau", "grupo"],
            value_vars=nota_cols,
            var_name="nota",
            value_name="pct",
        )
        dist["nota"] = dist["nota"].map(NOTAS)
        st.altair_chart(
            alt.Chart(dist)
            .mark_bar()
            .encode(
                x=alt.X("nota:O", title="Nota final", axis=alt.Axis(labelAngle=0)),
                xOffset="grupo:N",
                y=alt.Y("pct:Q", title="% dos diplomados"),
                color=alt.Color(
                    "grupo:N",
                    title=None,
                    scale=alt.Scale(
                        domain=["IPT", "Politécnicos públicos"],
                        range=[COR_IPT, COR_OUTROS],
                    ),
                ),
                column=alt.Column("Grau:N", title=None),
                tooltip=["Grau", "grupo", "nota", alt.Tooltip("pct:Q", format=".1f")],
            )
            .properties(width=320, height=240)
        )

        st.markdown("#### Evolução da nota média no IPT")
        ev = ponderada(cf, ["edicao", "Grau"], ["NotaFinalMedia"], W_NOTA)
        st.altair_chart(
            linhas(
                ev,
                "edicao",
                "NotaFinalMedia",
                "Grau",
                "Nota final média",
                escala=CORES_GRAU,
                zero=False,
            ),
            width="stretch",
        )

        st.markdown("#### Comparação com as outras escolas")
        grau = st.radio(
            "Grau:", ["CTeSP", "Licenciatura"], horizontal=True, key="g_nota"
        )
        ranking(cf_cmp, grau, "nota_media", "Nota final média", fmt=".2f")

# ---------------------------------------------------------------- dados
with tabs[6]:
    st.subheader("Dados e método")
    st.markdown("""
- **Perfil e procura** = todos os inscritos no curso (não só os que entraram nesse ano), InfoCursos.
- **Abandono** = alunos *não encontrados no ensino superior* 1 ano após entrar (InfoCursos).
  Não é igual a abandono: pode ser estrangeiro, emprego ou regresso mais tarde.
- **Em que ano saem** (1.º ano vs 2.º ano ou depois) = a mesma coorte seguida em duas folhas da
  InfoCursos, ligadas curso a curso (`ic_Percurso Coorte`): *Situação após 1 ano* (cada edição
  junta duas coortes de entrada) e *Taxa de conclusão* (uma coorte por edição; juntam-se duas).
  “Saiu no 2.º ano ou depois” = ainda estava no curso 1 ano depois de entrar, mas não o concluiu
  até 3 anos após o tempo esperado. Inclui quem mudou de curso mais tarde e os poucos ainda
  inscritos. Só entram cursos com taxa de conclusão publicada para todas as suas coortes.
- **Prosseguimento** = situação 1 ano após *concluir* o CTeSP (relatórios DGEEC por instituição).
  É uma medida diferente do abandono, sobre outro grupo de alunos.
- **Notas** = classificação final dos diplomados; a média das outras escolas é calculada a partir
  da distribuição por nota (10–20).
- As médias de escola são **ponderadas pelo n.º de alunos** de cada curso.
- Comparação = todos os politécnicos públicos, edição mais recente da InfoCursos.
- **Vagas**: nenhuma fonte pública agregada publica vagas e colocados dos CTeSP (são fixados
  por cada instituição), por isso a procura é medida pelos inscritos.
- Todo o processamento está em `pipeline/`; cada regra de limpeza está registada abaixo.
""")
    st.markdown("#### Registo de limpeza")
    st.dataframe(load("limpeza_log"), hide_index=True, width="stretch")
    st.markdown("#### Ficheiros de origem")
    st.dataframe(
        load("fontes"),
        hide_index=True,
        width="stretch",
        column_config={"url": st.column_config.LinkColumn()},
    )
