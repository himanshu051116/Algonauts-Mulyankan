"""
Seed script: loads YAML rule/scheme/rubric definitions into the database.

Run:  python -m backend.scripts.seed_data
"""

import asyncio
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import select

from app.database import async_session_factory, init_db
from app.models.proposal import (
    FundingScheme,
    GuidelineVersion,
    ModelVersion,
    RubricCriterion,
    RubricVersion,
    RuleDefinition,
)
from app.ml.constants import MODEL_NAME, MODEL_REGISTRY_ID, MODEL_REGISTRY_VERSION
from app.services.model_registry import (
    CONTEXTUAL_BASELINE_NAME,
    CONTEXTUAL_BASELINE_VERSION,
    brochure_ml_artifact_hash,
    brochure_ml_metadata,
    brochure_ml_quality_report,
    contextual_baseline_artifact_hash,
)
from app.services.schemes import ACTIVE_SCHEME_CODES

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
ACTIVE_SCHEME_CODE_SET = set(ACTIVE_SCHEME_CODES)



def is_active_seed_scheme(scheme_code: str) -> bool:
    """Only explicitly supported schemes may become active workflow data."""
    return scheme_code in ACTIVE_SCHEME_CODE_SET


async def seed():
    await init_db()
    async with async_session_factory() as db:
        # --- Seed funding schemes ---
        schemes_dir = DATA_DIR / "schemes"
        for path in sorted(schemes_dir.glob("*-scheme.yaml")):
            with open(path) as f:
                data = yaml.safe_load(f)
            scheme_code = data["scheme_code"]
            is_active = is_active_seed_scheme(scheme_code)
            existing = await db.execute(select(FundingScheme).where(FundingScheme.code == scheme_code))
            existing_scheme = existing.scalar_one_or_none()
            if existing_scheme:
                existing_scheme.name = data["name"]
                existing_scheme.description = data.get("description")
                existing_scheme.is_active = is_active
                print(f"  = Scheme: {scheme_code} ({'active' if is_active else 'inactive draft'})")
                continue
            scheme = FundingScheme(
                code=scheme_code,
                name=data["name"],
                description=data.get("description"),
                is_active=is_active,
            )
            db.add(scheme)
            await db.flush()
            print(f"  + Scheme: {scheme_code} ({'active' if is_active else 'inactive draft'})")

        await db.commit()

        # --- Seed guidelines from rule YAML files ---
        rules_dir = DATA_DIR / "rules"
        for path in sorted(rules_dir.glob("*-eligibility-rules-*.yaml")):
            with open(path) as f:
                data = yaml.safe_load(f)
            if not is_active_seed_scheme(data["scheme_code"]):
                print(f"  - Skipping inactive draft rules for {data['scheme_code']}")
                continue
            scheme_result = await db.execute(
                select(FundingScheme).where(FundingScheme.code == data["scheme_code"])
            )
            scheme_row = scheme_result.scalar_one_or_none()
            if not scheme_row:
                print(f"  ! Scheme {data['scheme_code']} not found for {path.name}, skipping")
                continue

            existing_gv = await db.execute(
                select(GuidelineVersion).where(
                    GuidelineVersion.scheme_id == scheme_row.id,
                    GuidelineVersion.version == data["rule_version"],
                )
            )
            if not existing_gv.scalar_one_or_none():
                gv = GuidelineVersion(
                    scheme_id=scheme_row.id,
                    version=data["rule_version"],
                    effective_date=datetime.strptime(
                        data["effective_date"], "%Y-%m-%d"
                    ),
                    content=data,
                )
                db.add(gv)
                await db.flush()
                print(f"  + Guideline v{data['rule_version']} for {data['scheme_code']}")

                for rule in data.get("rules", []):
                    existing_rule = await db.execute(
                        select(RuleDefinition).where(RuleDefinition.rule_id == rule["rule_id"])
                    )
                    if existing_rule.scalar_one_or_none():
                        continue
                    rd = RuleDefinition(
                        rule_id=rule["rule_id"],
                        guideline_version_id=gv.id,
                        funding_scheme_id=scheme_row.id,
                        category=rule["category"],
                        field=rule["field"],
                        operator=rule["operator"],
                        limit_value=(
                            str(rule["limit_value"])
                            if not isinstance(rule.get("limit_value"), list)
                            else ",".join(rule["limit_value"])
                        )
                        if rule.get("limit_value") is not None
                        else None,
                        severity=rule.get("severity", "error"),
                        uncertainty_action=rule.get("uncertainty_action", "review"),
                        source_reference=rule.get("source_reference"),
                        effective_date=datetime.strptime(
                            data["effective_date"], "%Y-%m-%d"
                        ),
                        is_active=is_active_seed_scheme(data["scheme_code"]),
                    )
                    db.add(rd)
                print(f"    -> {len(data.get('rules', []))} rules loaded")
            await db.commit()

        # --- Seed rubrics ---
        for path in sorted(rules_dir.glob("*-100-mark-rubric-*.yaml")):
            with open(path) as f:
                data = yaml.safe_load(f)
            if not is_active_seed_scheme(data["scheme_code"]):
                print(f"  - Skipping inactive draft rubric for {data['scheme_code']}")
                continue
            scheme_result = await db.execute(
                select(FundingScheme).where(FundingScheme.code == data["scheme_code"])
            )
            scheme_row = scheme_result.scalar_one_or_none()
            if not scheme_row:
                print(f"  ! Scheme {data['scheme_code']} not found for rubric {path.name}, skipping")
                continue

            existing_rv = await db.execute(
                select(RubricVersion).where(
                    RubricVersion.scheme_id == scheme_row.id,
                    RubricVersion.version == data["rubric_version"],
                )
            )
            if not existing_rv.scalar_one_or_none():
                rv = RubricVersion(
                    scheme_id=scheme_row.id,
                    version=data["rubric_version"],
                    effective_date=datetime.strptime(
                        data["effective_date"], "%Y-%m-%d"
                    ),
                    total_marks=data.get("total_marks", 100),
                    is_active=False,
                )
                db.add(rv)
                await db.flush()
                print(f"  + Rubric v{data['rubric_version']} for {data['scheme_code']}")

                order = 0
                for category in data.get("categories", []):
                    cat_name = category["name"]
                    for criterion in category.get("criteria", []):
                        rc = RubricCriterion(
                            rubric_version_id=rv.id,
                            criterion_key=criterion["id"],
                            category=cat_name,
                            criterion=criterion.get("label", criterion["id"]),
                            maximum=criterion["maximum"],
                            weight=1.0,
                            description=criterion.get("description"),
                            order=order,
                        )
                        db.add(rc)
                        order += 1
                print(f"    -> {order} criteria loaded")
            await db.commit()

        # --- Select the latest effective rubric for each active scheme ---
        active_scheme_result = await db.execute(
            select(FundingScheme).where(FundingScheme.code.in_(ACTIVE_SCHEME_CODES))
        )
        active_schemes = list(active_scheme_result.scalars().all())
        selected_rubrics: dict[str, RubricVersion] = {}
        for scheme in active_schemes:
            rubric_rows = await db.execute(
                select(RubricVersion)
                .where(RubricVersion.scheme_id == scheme.id)
                .order_by(RubricVersion.effective_date.desc(), RubricVersion.published_at.desc())
            )
            rubrics = list(rubric_rows.scalars().all())
            if not rubrics:
                continue
            selected = rubrics[0]

            # Deactivate every version first and flush separately so the
            # partial unique index never sees two active rubrics.
            for rubric in rubrics:
                rubric.is_active = False
            await db.flush()

            selected.is_active = True
            await db.flush()

            selected_rubrics[scheme.code] = selected
            print(f"  = Active rubric for {scheme.code}: v{selected.version}")
        await db.commit()

        # --- Register the trained brochure model and deterministic fallback ---
        active_rv = selected_rubrics.get("MOC-ST")
        if active_rv:
            all_models_result = await db.execute(select(ModelVersion))
            all_models = list(all_models_result.scalars().all())
            for model in all_models:
                model.is_active = False
            # Flush deactivations before any new active row is inserted so the
            # partial unique index never observes two active engines.
            await db.flush()

            baseline = next(
                (
                    model for model in all_models
                    if model.model_name == CONTEXTUAL_BASELINE_NAME
                    and model.version == CONTEXTUAL_BASELINE_VERSION
                ),
                None,
            )
            baseline_metadata = {
                "engine_type": "deterministic_contextual_baseline",
                "official_decision_validated": False,
                "trained_model": False,
                "notes": "Transparent fallback only; requires human review.",
            }
            if baseline is None:
                baseline = ModelVersion(
                    id=CONTEXTUAL_BASELINE_NAME,
                    model_name=CONTEXTUAL_BASELINE_NAME,
                    version=CONTEXTUAL_BASELINE_VERSION,
                    artifact_hash=contextual_baseline_artifact_hash(),
                    rubric_version_id=active_rv.id,
                    training_rows=0,
                    test_metrics=baseline_metadata,
                    lifecycle_state="bootstrap",
                    quality_gate_report_hash=None,
                    is_active=False,
                )
                db.add(baseline)
                print(f"  + Fallback ModelVersion: {CONTEXTUAL_BASELINE_NAME}")
            else:
                baseline.version = CONTEXTUAL_BASELINE_VERSION
                baseline.artifact_hash = contextual_baseline_artifact_hash()
                baseline.rubric_version_id = active_rv.id
                baseline.training_rows = 0
                baseline.test_metrics = baseline_metadata
                baseline.lifecycle_state = "bootstrap"
                baseline.quality_gate_report_hash = None
                baseline.is_active = False
                print(f"  = Fallback ModelVersion: {CONTEXTUAL_BASELINE_NAME}")

            try:
                model_card = brochure_ml_metadata()
                quality_report = brochure_ml_quality_report()
                metrics = model_card.get("metrics", {})
                if not isinstance(metrics, dict):
                    raise RuntimeError("Packaged ML metrics must be an object")
                registry_metrics = {
                    **metrics,
                    "random_seed": model_card.get("random_seed"),
                    "label_origin": model_card.get("label_origin"),
                    "official_decision_validated": False,
                    "trained_model": True,
                    "quality_gate_report_hash": quality_report["report_sha256"],
                    "lifecycle_state": quality_report["promotion"][
                        "recommended_state"
                    ],
                }
                trained = next(
                    (
                        model for model in all_models
                        if model.model_name == MODEL_NAME
                        and model.version == MODEL_REGISTRY_VERSION
                    ),
                    None,
                )
                if trained is None:
                    trained = ModelVersion(
                        id=MODEL_REGISTRY_ID,
                        model_name=MODEL_NAME,
                        version=MODEL_REGISTRY_VERSION,
                        artifact_hash=brochure_ml_artifact_hash(),
                        rubric_version_id=active_rv.id,
                        training_rows=int(model_card.get("training_rows", 0)),
                        test_metrics=registry_metrics,
                        lifecycle_state=quality_report["promotion"][
                            "recommended_state"
                        ],
                        quality_gate_report_hash=quality_report["report_sha256"],
                        is_active=True,
                    )
                    db.add(trained)
                    print(f"  + Active trained ModelVersion: {MODEL_NAME}")
                else:
                    trained.version = MODEL_REGISTRY_VERSION
                    trained.artifact_hash = brochure_ml_artifact_hash()
                    trained.rubric_version_id = active_rv.id
                    trained.training_rows = int(model_card.get("training_rows", 0))
                    trained.test_metrics = registry_metrics
                    trained.lifecycle_state = quality_report["promotion"][
                        "recommended_state"
                    ]
                    trained.quality_gate_report_hash = quality_report["report_sha256"]
                    trained.is_active = True
                    print(f"  = Active trained ModelVersion: {MODEL_NAME}")
            except RuntimeError as exc:
                baseline.is_active = True
                print(f"  ! Trained ML model unavailable; activated fallback: {exc}")
        else:
            print("  ! No active MOC-ST rubric found; model versions were not seeded")
        await db.commit()

        print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
