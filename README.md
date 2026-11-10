# CTeSP no Politécnico de Tomar (IPT / UPTomar)

Recolha reprodutível de dados públicos sobre os CTeSP do IPT (abandono, prosseguimento
para licenciatura, conclusão) e comparação com as licenciaturas.

## Como correr

```bash
uv sync
uv run python -m pipeline            # fetch + build + clean
uv run python -m pipeline fetch      # 1. descarrega o que falta     -> data/raw/
uv run python -m pipeline build      # 2. extrai as linhas do IPT    -> data/interim/
uv run python -m pipeline clean      # 3. limpa para análise         -> data/processed/
uv run python -m pipeline fetch --force   # volta a descarregar tudo
```

## `sources.csv` (editado à mão)

| coluna | significado |
| --- | --- |
| `id` | nome único; ficheiros vão para `data/raw/<id>/` |
| `enabled` | `1` descarrega, `0` ignora |
| `kind` | `file` = descarrega o `url` tal como está · `index` = abre a página `url` e descarrega os links que batem com `link_pattern` |
| `parser` | extrator a usar: `infocursos`, `dgeec_ctesp`, `dgeec_licenciatura` ou `none` (só guardar) |
| `url` | link base |
| `link_pattern` | (só `index`) regex dos links; o grupo 1 serve para ordenar |
| `select` | (só `index`) `all` ou `latest` |
| `description` | texto livre |

**Reutilizar noutro ano:** a InfoCursos é `kind=index`, por isso a edição nova
(`Infocursos_2027.xlsx`, …) é apanhada sozinha. Quando a DGEEC publicar um relatório
novo de prosseguimento por IES, acrescenta uma linha `file` com o link `api/ficheiros/...`
e o `parser` respetivo. A instituição e o grupo de comparação estão em `pipeline/config.py`.

## Saídas

- `data/manifest.csv`: proveniência de cada ficheiro (URL, data, sha256, bytes). Gerado.
- `data/raw/`: ficheiros originais (fora do git; recriados pelo `fetch`).
- `data/interim/ipt_extraido.xlsx` (+ CSVs): linhas do IPT tal como vêm da fonte.
  - `ic_<folha>`: todas as edições da InfoCursos (coluna `edicao`)
  - `ic_cmp_<folha>`: edição mais recente, média ponderada por politécnico público × grau
  - `dg_ctesp_ipt` / `dg_ctesp_nacional`: situação dos diplomados CTeSP no ano seguinte
  - `dg_lic_ipt` / `dg_lic_nacional`: o mesmo para licenciados (comparação)
  - `dg_*_todas`: todas as linhas de todos os relatórios, para auditar sobreposições
  - `fontes`: cópia do manifest
- `data/processed/ipt_limpo.xlsx` (+ CSVs): **usar este para a análise.** Mesmas folhas,
  limpas pelas regras de `pipeline/clean.py`, mais `limpeza_log` (regra, folha, n.º afetados):
  1. só CTeSP e Licenciatura (mestrados fora)
  2. rótulos uniformizados (`Licenciatura 1.º ciclo` → `Licenciatura`, `Publico` → `Público`, …)
  3. colunas renomeadas entre edições (ex.: `PercentagemAindaInscritosCurso` →
     `PercentagemInscritosMesmoEstabelecimentoCurso`, até à edição 2021)
  4. folhas renomeadas juntas (`Idades` → `Inscritos por Idade`)
  5. folhas com o ano no nome da coluna (`Numero Inscritos`, `Percentil Entrada`) passam a
     formato longo, uma linha por curso × ano, fica a edição mais recente
  6. percentis 0–1 → 0–100; valores fora do intervalo válido → vazio
  7. linhas sem nenhum indicador (suprimidas na fonte) e anos com 0 inscritos removidos
  8. colunas vazias e linhas duplicadas removidas
  9. amostras pequenas (`n ≤ MAX_N_PEQUENA` = 5, em `config.py`) **sinalizadas** em `amostra_pequena`, não removidas

## Notas de método

- Nos PDFs da DGEEC o ano é atribuído pela ordem das linhas (igual à da Tabela 1). Se o
  número de linhas não bater certo, a coluna `verificar` fica preenchida.
- "Não encontrado no ensino superior" não é o mesmo que abandono (pode ser estrangeiro,
  emprego, regresso mais tarde).
- Abandono (1 ano após entrar) e prosseguimento (1 ano após concluir) são medidas diferentes.
- Na InfoCursos, `Desemprego Registado` e `Formas Ingresso` só têm licenciaturas.
