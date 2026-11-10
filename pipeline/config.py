"""Project settings. Change these when the project is reused in later years."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_CSV = ROOT / "sources.csv"
RAW_DIR = ROOT / "data" / "raw"  # 1. fetch: original files
INTERIM_DIR = (
    ROOT / "data" / "interim"
)  # 2. build: extracted, filtered to the institution
PROCESSED_DIR = ROOT / "data" / "processed"  # 3. clean: ready for analysis
MANIFEST_CSV = ROOT / "data" / "manifest.csv"
INTERIM_XLSX = INTERIM_DIR / "ipt_extraido.xlsx"
OUTPUT_XLSX = PROCESSED_DIR / "ipt_limpo.xlsx"

# Rows with this many students or fewer are flagged (amostra_pequena), not dropped.
MAX_N_PEQUENA = 5

# Institution of interest. InfoCursos is filtered by code first, then by name;
# the DGEEC PDFs only have the short name ("I.P. Tomar", "I. P. de Tomar").
# The name regex also matches "Universidade Politécnica de Tomar".
INSTITUTION_CODE = "3240"
INSTITUTION_NAME_REGEX = r"Tomar"

# Comparison group for InfoCursos benchmarks (column "TipoEnsino" / "Natureza").
PEER_TIPO_ENSINO = "Politécnico"
PEER_NATUREZA = "Público"

# Degree labels used in InfoCursos "Grau" column that are compared.
GRAUS_COMPARACAO = ["CTeSP", "Licenciatura 1.º ciclo", "Licenciatura"]

USER_AGENT = "understanding-education-entry/0.1 (academic project)"
