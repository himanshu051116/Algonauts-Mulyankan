"""Identity and paths for the packaged brochure-aligned ML model."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"

MODEL_NAME = "moc-brochure-hybrid-ml-v2"
MODEL_VERSION = "2.0"  # Statistical artifact/card version.
MODEL_REGISTRY_VERSION = "2.1"  # Evidence-gated inference policy version.
MODEL_REGISTRY_ID = "moc-brochure-hybrid-ml-v2-evidence-v1"
MODEL_FORMAT_VERSION = "portable-hashed-linear-v1"
MODEL_DIR: Path = DATA_DIR / "models" / MODEL_NAME
MODEL_ARTIFACT_PATH: Path = MODEL_DIR / "model.npz"
MODEL_CARD_PATH: Path = MODEL_DIR / "model_card.json"
MODEL_METRICS_PATH: Path = MODEL_DIR / "metrics.json"
MODEL_QUALITY_REPORT_PATH: Path = MODEL_DIR / "model_quality_gate_report.json"
MODEL_RUBRIC_PATH: Path = DATA_DIR / "rules" / "moc-st-100-mark-rubric-v2.yaml"
MODEL_EVIDENCE_CONTRACT_PATH: Path = (
    DATA_DIR / "evidence-contracts" / "moc-st-evidence-contracts-v1.yaml"
)
MODEL_BENCHMARK_PATH: Path = (
    DATA_DIR / "benchmarks" / "no-private-data-advisory-ml-v1.json"
)
