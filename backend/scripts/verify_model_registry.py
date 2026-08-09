"""Verify that the active MOC-ST model registry matches packaged artifacts."""

from __future__ import annotations

import asyncio

from app.database import async_session_factory
from app.services.model_registry import (
    brochure_ml_artifact_hash,
    select_active_model_version,
)

SCHEME_CODE = "MOC-ST"


async def verify() -> None:
    expected = brochure_ml_artifact_hash()
    async with async_session_factory() as session:
        model = await select_active_model_version(session, SCHEME_CODE)
        print(f"scheme={SCHEME_CODE}")
        print(f"model_id={model.id}")
        print(f"model_name={model.model_name}")
        print(f"model_version={model.version}")
        print(f"registered_artifact_hash={model.artifact_hash}")
        print(f"packaged_artifact_hash={expected}")
        if model.artifact_hash != expected:
            raise RuntimeError(
                "The active MOC-ST registry hash does not match the packaged evaluator"
            )
        print("model_registry_verification=ok")


if __name__ == "__main__":
    asyncio.run(verify())
