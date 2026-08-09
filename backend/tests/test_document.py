"""Unit tests for the document extraction service."""

import tempfile
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.services.document import (
    compute_file_hash,
    detect_sections,
    extract_structured_fields,
    normalize_project_duration,
)


@pytest.mark.asyncio
async def test_detect_sections():
    text = """
    Abstract
    This is the abstract of the proposal.

    Introduction
    Background and context for the research.

    Objectives
    The main objectives of this project are...

    Methodology
    We will use the following methods...

    Budget
    The total budget is 50 lakhs.

    References
    [1] Some reference
    """
    sections = await detect_sections(text)
    types = {s["section_type"] for s in sections}
    assert "abstract" in types
    assert "introduction" in types
    assert "objectives" in types
    assert "methodology" in types
    assert "budget" in types
    assert "references" in types


@pytest.mark.asyncio
async def test_extract_structured_fields_duration():
    text = "The project duration is 24 months."
    fields = await extract_structured_fields(text)
    durations = [f for f in fields if f["field_name"] == "project_duration"]
    assert len(durations) == 1
    assert durations[0]["normalized_value"] == 24
    assert durations[0]["unit"] == "months"
    assert durations[0]["original_text"] == "project duration is 24 months"


@pytest.mark.asyncio
async def test_extract_structured_fields_contingency():
    text = "Contingency is 4% of the budget."
    fields = await extract_structured_fields(text)
    contingencies = [f for f in fields if f["field_name"] == "contingency_percentage"]
    assert len(contingencies) == 1
    assert contingencies[0]["field_value"] == "4"


@pytest.mark.asyncio
async def test_extract_structured_fields_trl():
    text = "Current TRL: 4, target TRL: 6."
    fields = await extract_structured_fields(text)
    trls = [f for f in fields if f["field_name"] == "trl"]
    assert len(trls) >= 1


@pytest.mark.asyncio
async def test_extract_structured_fields_for_active_moc_st_rules():
    text = """
    Institution Type: research institute
    PI Qualification: PhD in mining engineering
    Project Duration: 24 months
    Thrust Area: safety-health-environment
    Contingency: 4%
    Overhead: 8%
    Foreign Travel: none
    Staff Vehicles: none
    Permanent Salary: none
    Equipment Duplication: no duplication
    DGMS Approval: required for mine safety field trials
    """
    fields = {field["field_name"]: field for field in await extract_structured_fields(text)}

    assert fields["institution_eligibility"]["normalized_value"] == "research_institute"
    assert fields["pi_qualification"]["normalized_value"] == "phd"
    assert fields["project_duration"]["normalized_value"] == 24
    assert fields["thrust_area_alignment"]["normalized_value"] == "safety-health-environment"
    assert fields["contingency_percentage"]["normalized_value"] == "4"
    assert fields["overhead_percentage"]["normalized_value"] == "8"
    assert fields["foreign_travel"]["normalized_value"] == "none"
    assert fields["staff_vehicles"]["normalized_value"] == "none"
    assert fields["permanent_salary"]["normalized_value"] == "none"
    assert fields["equipment_duplication"]["normalized_value"] == "none"
    assert fields["dgms_approval"]["normalized_value"] == "required for mine safety field trials"




@pytest.mark.asyncio
async def test_prohibited_item_negation_in_free_prose_is_not_misread_as_spend():
    text = (
        "The requested budget has no foreign travel, and contingency remains below five percent. "
        "No foreign travel is proposed for institutional field visits."
    )
    fields = {field["field_name"]: field for field in await extract_structured_fields(text)}

    assert fields["foreign_travel"]["normalized_value"] == "none"
    assert "no foreign travel" in fields["foreign_travel"]["original_text"].lower()


@pytest.mark.asyncio
async def test_prohibited_item_explicit_positive_declaration_still_fails_closed():
    text = "Foreign Travel: included, INR 8 lakh budgeted for an overseas visit."
    fields = {field["field_name"]: field for field in await extract_structured_fields(text)}

    assert fields["foreign_travel"]["normalized_value"] == "yes"




@pytest.mark.asyncio
async def test_industry_relevance_resolves_from_partner_and_deployment_signals():
    text = (
        "The proposal includes an industry deployment plan and a named industry partner. "
        "A separately governed field demonstration and technology transfer pathway are defined."
    )
    fields = {field["field_name"]: field for field in await extract_structured_fields(text)}

    assert fields["industry_relevance"]["normalized_value"] == "demonstrated"


@pytest.mark.asyncio
async def test_compute_file_hash():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test content")
        tmp_path = f.name
    try:
        h = await compute_file_hash(tmp_path)
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Project duration is 18 months.", 18),
        ("The project period is 2 years.", 24),
        ("The duration is two years.", 24),
        ("Project duration: 1.5 years.", 18),
        ("The schedule is 24-month.", 24),
        ("The schedule is 24 month.", 24),
        ("A 2-year project is proposed.", 24),
    ],
)
def test_normalize_project_duration_supported_forms(text, expected):
    result = normalize_project_duration(text)
    assert result["normalized_value"] == expected
    assert result["unit"] == "months"
    assert result["status"] == "resolved"
    assert result["original_text"]


def test_normalize_project_duration_conflicting_values():
    result = normalize_project_duration("Project duration is 18 months, but the schedule says 2 years.")
    assert result["normalized_value"] is None
    assert result["status"] == "clarification_required"
    assert "Contradictory" in result["validation_warnings"][0]


def test_normalize_project_duration_missing_value():
    result = normalize_project_duration("The schedule will be provided later.")
    assert result["normalized_value"] is None
    assert result["status"] == "unresolved"


@pytest.mark.asyncio
async def test_valid_fixture_resolves_duration_markdown_and_pi_qualification():
    from app.services.field_schema import canonicalize_extracted_fields
    from app.services.rules import evaluate_rules

    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "fixtures"
        / "valid-proposal.md"
    )
    fixture = fixture_path.read_text(encoding="utf-8")
    canonical = canonicalize_extracted_fields(await extract_structured_fields(fixture))
    assert canonical["fields"]["project_duration"]["normalized_value"] == 24
    assert canonical["fields"]["pi_qualification"]["normalized_value"] == "phd"
    assert canonical["fields"]["contingency_percentage"]["normalized_value"] == "3"
    assert canonical["fields"]["overhead_percentage"]["normalized_value"] == "10"
    result = await evaluate_rules("MOC-ST", canonical)
    assert result["summary"]["automatic_progression"] is True
    assert result["summary"]["blocking_statuses"] == []


def _write_docx_package(
    path: Path,
    *,
    active_content: bool = False,
    document_xml_override: str | None = None,
) -> None:
    import zipfile

    content_type = (
        "application/vnd.ms-word.document.macroEnabled.main+xml"
        if active_content
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    )
    content_types = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Override PartName="/word/document.xml" ContentType="{content_type}"/>
    </Types>'''
    document_xml = document_xml_override or '''<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Coal safety proposal</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Milestone</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>Month 6</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/media/figure.png", b"not-a-real-image")
        if active_content:
            archive.writestr("word/vbaProject.bin", b"macro")


def test_validate_docx_package_rejects_active_content(tmp_path: Path):
    from app.services.document import validate_docx_package

    path = tmp_path / "macro.docx"
    _write_docx_package(path, active_content=True)

    with pytest.raises(ValueError, match="docx_active_content_not_allowed"):
        validate_docx_package(str(path))


def test_validate_docx_package_rejects_xml_entities(tmp_path: Path):
    from app.services.document import validate_docx_package

    path = tmp_path / "entity.docx"
    document_xml = '''<?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE document [<!ENTITY injected "expanded content">]>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>&injected;</w:t></w:r></w:p></w:body>
    </w:document>'''
    _write_docx_package(path, document_xml_override=document_xml)

    with pytest.raises(ValueError, match="docx_invalid_xml"):
        validate_docx_package(str(path))


def test_validate_docx_package_checks_member_sizes_before_reading(
    tmp_path: Path,
    monkeypatch,
):
    from app.services import document

    path = tmp_path / "oversized-member.docx"
    path.write_bytes(b"PK")

    class FakeInfo:
        def __init__(self, filename: str, file_size: int = 1):
            self.filename = filename
            self.file_size = file_size
            self.compress_size = 1
            self.flag_bits = 0

    class FakeArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def infolist(self):
            return [
                FakeInfo(
                    "[Content_Types].xml",
                    document.MAX_DOCX_MEMBER_BYTES + 1,
                ),
                FakeInfo("_rels/.rels"),
                FakeInfo("word/document.xml"),
            ]

        def read(self, _name):
            raise AssertionError("archive content was read before metadata validation")

    monkeypatch.setattr(document.zipfile, "is_zipfile", lambda _path: True)
    monkeypatch.setattr(document.zipfile, "ZipFile", lambda _path: FakeArchive())

    with pytest.raises(ValueError, match="docx_member_size_limit_exceeded"):
        document.validate_docx_package(str(path))


def test_ocr_confidence_is_normalized_for_database_storage(monkeypatch):
    from app.services import document

    fake_pytesseract = ModuleType("pytesseract")
    fake_pytesseract.Output = SimpleNamespace(DICT="dict")
    fake_pytesseract.image_to_data = lambda *_args, **_kwargs: {
        "text": ["Coal", "safety", "", "proposal"],
        "conf": ["90", "70", "99", "-1"],
    }
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    text, confidence = document._ocr_image(object())

    assert text == "Coal safety proposal"
    assert confidence == 0.8


def test_docx_inventory_extracts_tables_and_images(tmp_path: Path):
    from app.services.document import _docx_inventory, validate_docx_package

    path = tmp_path / "proposal.docx"
    _write_docx_package(path)
    validate_docx_package(str(path))

    tables, images = _docx_inventory(str(path))
    assert tables[0]["rows"] == [["Milestone", "Month 6"]]
    assert images[0]["file_name"] == "figure.png"
