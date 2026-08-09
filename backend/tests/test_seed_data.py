from scripts.seed_data import is_active_seed_scheme


def test_seed_marks_only_moc_st_as_active_workflow_data():
    assert is_active_seed_scheme("MOC-ST") is True
    assert is_active_seed_scheme("CIL-RD") is False
    assert is_active_seed_scheme("ST-FIRST") is False


def test_baseline_artifact_hash_is_reproducible_and_non_placeholder():
    from app.services.model_registry import contextual_baseline_artifact_hash

    first = contextual_baseline_artifact_hash()
    second = contextual_baseline_artifact_hash()
    assert first == second
    assert len(first) == 64
    assert first != "0" * 64
