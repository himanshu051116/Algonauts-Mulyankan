"""Secure server-side document extraction and structured-field detection.

The extraction pipeline keeps page boundaries, uses native text first, falls
back to Hindi/English OCR only for text-poor PDF pages, and returns evidence
locations that can be persisted for audit-grade review.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.config import settings

MAX_PDF_PAGES = 200
MAX_EXTRACTED_TEXT_CHARS = 500_000
MAX_DOCX_BYTES = 25 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
MAX_DOCX_MEMBERS = 5000
MAX_DOCX_MEMBER_BYTES = 50 * 1024 * 1024
MIN_NATIVE_WORDS_PER_PAGE = 20
OCR_RESOLUTION_DPI = 220
OCR_TIMEOUT_SECONDS = 45


def validate_docx_package(file_path: str) -> None:
    """Validate that a ZIP upload is a safe, structurally valid DOCX package."""

    path = Path(file_path)
    if path.stat().st_size > MAX_DOCX_BYTES:
        raise ValueError("docx_size_limit_exceeded")
    if not zipfile.is_zipfile(path):
        raise ValueError("docx_invalid_package")

    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_DOCX_MEMBERS:
            raise ValueError("docx_member_limit_exceeded")
        names = {info.filename.replace("\\", "/") for info in infos}
        required = {"[Content_Types].xml", "word/document.xml", "_rels/.rels"}
        if not required.issubset(names):
            raise ValueError("docx_invalid_package")
        if any(
            name.lower().endswith("vbaproject.bin")
            or name.lower().startswith("word/embeddings/")
            for name in names
        ):
            raise ValueError("docx_active_content_not_allowed")

        total_uncompressed = 0
        for info in infos:
            member = Path(info.filename.replace("\\", "/"))
            if member.is_absolute() or ".." in member.parts:
                raise ValueError("docx_unsafe_member_path")
            if info.flag_bits & 0x1:
                raise ValueError("docx_encrypted_member_not_allowed")
            if info.file_size > MAX_DOCX_MEMBER_BYTES:
                raise ValueError("docx_member_size_limit_exceeded")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ValueError("docx_uncompressed_size_limit_exceeded")
            if info.compress_size > 0 and info.file_size / info.compress_size > 2000:
                raise ValueError("docx_suspicious_compression_ratio")

        # Parse XML only after every archive entry has passed the metadata
        # checks. Mammoth must never receive entity-expanding OOXML content.
        content_types = b""
        for info in infos:
            name = info.filename.replace("\\", "/")
            if not name.lower().endswith((".xml", ".rels")):
                continue
            try:
                payload = archive.read(info)
                ElementTree.fromstring(payload)
            except (DefusedXmlException, ElementTree.ParseError) as exc:
                raise ValueError("docx_invalid_xml") from exc
            except (KeyError, OSError, zipfile.BadZipFile) as exc:
                raise ValueError("docx_invalid_package") from exc
            if name == "[Content_Types].xml":
                content_types = payload.lower()

        if b"macroenabled" in content_types or b"vnd.ms-word" in content_types:
            raise ValueError("docx_active_content_not_allowed")


def _docx_inventory(file_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract bounded table and image inventories from the validated package."""

    word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    tables: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    with zipfile.ZipFile(file_path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        for table_number, table in enumerate(
            root.findall(f".//{{{word_namespace}}}tbl"), start=1
        ):
            rows: list[list[str]] = []
            for row in table.findall(f"./{{{word_namespace}}}tr"):
                cells: list[str] = []
                for cell in row.findall(f"./{{{word_namespace}}}tc"):
                    text = " ".join(
                        value.strip()
                        for node in cell.findall(f".//{{{word_namespace}}}t")
                        if (value := (node.text or "")).strip()
                    )
                    cells.append(text)
                rows.append(cells)
            tables.append({"table_number": table_number, "rows": rows})

        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if name.lower().startswith("word/media/") and not name.endswith("/"):
                images.append(
                    {
                        "path": name,
                        "file_name": Path(name).name,
                        "size_bytes": info.file_size,
                    }
                )
    return tables, images


def _ocr_image(image: Any) -> tuple[str, float | None]:
    """Run OCR in a worker thread and return text plus mean confidence."""

    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(
        image,
        lang=settings.ocr_language,
        config="--psm 6",
        output_type=Output.DICT,
        timeout=OCR_TIMEOUT_SECONDS,
    )
    tokens: list[str] = []
    confidences: list[float] = []
    for token, raw_confidence in zip(data.get("text", []), data.get("conf", []), strict=False):
        cleaned = str(token).strip()
        if not cleaned:
            continue
        tokens.append(cleaned)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            continue
        if 0 <= confidence <= 100:
            confidences.append(confidence)
    text = " ".join(tokens).strip()
    mean_confidence = (
        round(sum(confidences) / (len(confidences) * 100), 4)
        if confidences
        else None
    )
    return text, mean_confidence


async def extract_pdf(file_path: str) -> dict[str, Any]:
    """Extract native text, tables, images and OCR fallback from a PDF."""

    try:
        import pdfplumber
    except ImportError:
        return {"text": "", "pages": [], "error": "pdfplumber_not_installed"}

    result: dict[str, Any] = {
        "text": "",
        "pages": [],
        "tables": [],
        "images": [],
        "metadata": {},
        "warnings": [],
        "ocr_pages": [],
    }

    with pdfplumber.open(file_path) as pdf:
        result["metadata"] = dict(pdf.metadata or {})
        if len(pdf.pages) > MAX_PDF_PAGES:
            return {
                **result,
                "error": "pdf_page_limit_exceeded",
                "warnings": [f"PDF exceeds maximum page count of {MAX_PDF_PAGES}"],
            }

        page_blocks: list[str] = []
        for page_num, page in enumerate(pdf.pages, 1):
            native_text = (page.extract_text() or "").strip()
            native_word_count = len(native_text.split())
            page_text = native_text
            ocr_used = False
            ocr_confidence: float | None = None

            if native_word_count < MIN_NATIVE_WORDS_PER_PAGE:
                try:
                    rendered = page.to_image(resolution=OCR_RESOLUTION_DPI).original
                    ocr_text, ocr_confidence = await asyncio.to_thread(_ocr_image, rendered)
                    if len(ocr_text.split()) > native_word_count:
                        page_text = ocr_text
                        ocr_used = True
                        result["ocr_pages"].append(page_num)
                except Exception as exc:  # OCR failure must not destroy native extraction.
                    result["warnings"].append(
                        f"OCR failed on page {page_num}: {type(exc).__name__}"
                    )

            tables = page.extract_tables() or []
            normalised_tables = [
                [[str(cell or "") for cell in row] for row in table]
                for table in tables
            ]
            for table in normalised_tables:
                result["tables"].append({"page": page_num, "rows": table})

            image_count = len(page.images or [])
            if image_count:
                result["images"].append({"page": page_num, "count": image_count})

            page_entry = {
                "page_number": page_num,
                "text": page_text,
                "word_count": len(page_text.split()),
                "native_word_count": native_word_count,
                "ocr_used": ocr_used,
                "ocr_confidence": ocr_confidence,
                "table_count": len(normalised_tables),
                "image_count": image_count,
                "tables": normalised_tables,
            }
            result["pages"].append(page_entry)
            page_blocks.append(f"[PAGE {page_num}]\n{page_text}")

    result["text"] = "\n\n".join(page_blocks).strip()
    if len(result["text"]) > MAX_EXTRACTED_TEXT_CHARS:
        return {
            **result,
            "text": "",
            "error": "pdf_text_limit_exceeded",
            "warnings": result["warnings"]
            + [f"Extracted PDF text exceeds {MAX_EXTRACTED_TEXT_CHARS} characters"],
        }
    return result


async def extract_docx(file_path: str) -> dict[str, Any]:
    """Extract text from a structurally validated DOCX file."""

    try:
        validate_docx_package(file_path)
    except ValueError as exc:
        code = str(exc)
        return {"text": "", "error": code, "warnings": [code]}

    try:
        import mammoth
    except ImportError:
        return {"text": "", "error": "mammoth_not_installed"}

    with open(file_path, "rb") as file:
        result = mammoth.extract_raw_text(file)

    text = result.value.strip()
    warnings = [str(w.message) for w in result.messages]
    if not text:
        return {"text": "", "error": "docx_text_missing", "warnings": warnings + ["No extractable text found"]}
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        return {
            "text": "",
            "error": "docx_text_limit_exceeded",
            "warnings": [f"Extracted DOCX text exceeds {MAX_EXTRACTED_TEXT_CHARS} characters"],
        }
    try:
        tables, images = _docx_inventory(file_path)
    except (
        DefusedXmlException,
        ElementTree.ParseError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
    ):
        return {
            "text": "",
            "error": "docx_invalid_xml",
            "warnings": warnings + ["The DOCX XML package could not be parsed safely"],
        }
    return {
        "text": text,
        "pages": [
            {
                "page_number": 1,
                "text": text,
                "word_count": len(text.split()),
                "ocr_used": False,
            }
        ],
        "warnings": warnings,
        "ocr_pages": [],
        "tables": tables,
        "images": images,
    }


async def compute_file_hash(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""

    sha256 = hashlib.sha256()
    with open(file_path, "rb") as file:
        while chunk := file.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def _page_for_offset(text: str, offset: int) -> int | None:
    page = None
    for match in re.finditer(r"\[PAGE\s+(\d+)\]", text[: max(0, offset) + 1], re.IGNORECASE):
        page = int(match.group(1))
    return page


async def detect_sections(text: str) -> list[dict[str, Any]]:
    """Detect proposal sections with page and character ranges."""

    section_patterns = {
        "abstract": ["abstract", "executive summary", "summary"],
        "introduction": ["introduction", "background"],
        "objectives": ["objectives", "aims and objectives", "aim of the study"],
        "literature_review": ["review of literature", "literature review", "prior work"],
        "methodology": ["methodology", "research methodology", "methods"],
        "work_plan": ["work plan", "workplan", "project implementation"],
        "budget": ["budget", "financial", "cost estimate"],
        "timeline": ["timeline", "milestone", "gantt chart", "schedule"],
        "team": ["project team", "principal investigator", "investigator"],
        "compliance": ["compliance", "statutory approval", "declaration"],
        "references": ["references", "bibliography"],
        "annexures": ["annexure", "appendix", "enclosure"],
    }

    lower_text = text.lower()
    detected: list[dict[str, Any]] = []
    for section_type, patterns in section_patterns.items():
        candidates = [(lower_text.find(pattern), pattern) for pattern in patterns]
        candidates = [(index, pattern) for index, pattern in candidates if index >= 0]
        if not candidates:
            continue
        index, heading = min(candidates, key=lambda item: item[0])
        detected.append(
            {
                "section_type": section_type,
                "heading": text[index : index + len(heading)],
                "char_start": index,
                "start_page": _page_for_offset(text, index),
                "confidence": 0.75,
            }
        )

    detected.sort(key=lambda section: int(section["char_start"]))
    for index, section in enumerate(detected):
        end = int(detected[index + 1]["char_start"]) if index + 1 < len(detected) else len(text)
        section["char_end"] = end
        section["end_page"] = _page_for_offset(text, max(int(section["char_start"]), end - 1))
        section["text"] = text[int(section["char_start"]) : end].strip()
    return detected


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "eighteen": 18,
    "twenty four": 24,
    "twenty-four": 24,
    "thirty six": 36,
    "thirty-six": 36,
}
_DURATION_VALUE = (
    r"\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|eighteen|twenty[- ]four|thirty[- ]six"
)


def _parse_duration_number(raw: str) -> float | None:
    cleaned = raw.strip().lower()
    if cleaned in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[cleaned])
    try:
        return float(cleaned)
    except ValueError:
        return None


def _duration_match_to_entry(match: re.Match[str]) -> dict[str, Any] | None:
    number = _parse_duration_number(match.group("value"))
    if number is None:
        return None
    unit = match.group("unit").lower()
    months = number * 12 if unit.startswith("year") else number
    normalized: int | float = int(months) if months.is_integer() else months
    return {
        "normalized_value": normalized,
        "unit": "months",
        "original_text": match.group("original"),
        "char_start": match.start(),
        "char_end": match.end(),
    }


def normalize_project_duration(text: str) -> dict[str, Any]:
    """Resolve overall project duration without mistaking milestone ranges.

    Explicit project-duration labels have the highest confidence.  A standalone
    overall schedule statement is also accepted, but schedule table rows and
    phase/milestone ranges are excluded.  Conflicting explicit overall values
    are returned for clarification rather than silently choosing one.
    """

    labelled_patterns = [
        re.compile(
            rf"(?P<original>(?:total\s+)?(?:project\s+)?(?:duration|project\s+period|period\s+of\s+project)"
            rf"\s*(?:is|of|:|-)?\s*[*_]*\s*(?P<value>{_DURATION_VALUE})\s*[- ]?\s*(?P<unit>months?|years?))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<original>(?:overall\s+)?schedule\s*(?:is|says|:|-)\s*(?P<value>{_DURATION_VALUE})"
            rf"\s*[- ]?\s*(?P<unit>months?|years?))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<original>(?:a|an|the)?\s*(?P<value>{_DURATION_VALUE})\s*[- ]?\s*(?P<unit>months?|years?)"
            rf"\s+project(?:\s+is\s+proposed)?)",
            re.IGNORECASE,
        ),
    ]
    matches: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in labelled_patterns:
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 60) : match.end() + 20].lower()
            if re.search(r"(?:phase|milestone|quarter|work\s*package)\s*\d*\s*[:=-]", context):
                continue
            entry = _duration_match_to_entry(match)
            if entry:
                matches.append(entry)
                occupied.append((match.start(), match.end()))

    if not matches:
        fallback_pattern = re.compile(
            rf"(?P<original>(?P<value>{_DURATION_VALUE})\s*[- ]?\s*(?P<unit>months?|years?))",
            re.IGNORECASE,
        )
        for match in fallback_pattern.finditer(text):
            context = text[max(0, match.start() - 55) : match.end() + 20].lower()
            immediate_prefix = text[max(0, match.start() - 5) : match.start()]
            if any(token in context for token in ("phase", "milestone", "quarter", "work package", "experience")):
                continue
            if re.search(r"\d\s*[-–—]\s*$", immediate_prefix):
                continue
            entry = _duration_match_to_entry(match)
            if entry:
                matches.append(entry)

    if not matches:
        return {
            "field_name": "project_duration",
            "normalized_value": None,
            "unit": "months",
            "original_text": None,
            "extraction_method": "duration_normalizer_v2",
            "evidence_coverage": 0.0,
            "validation_warnings": ["No parseable overall project duration found"],
            "status": "unresolved",
        }

    # De-duplicate overlapping regex matches while preserving genuine conflicts.
    unique_matches: list[dict[str, Any]] = []
    seen: set[tuple[int, int, object]] = set()
    for entry in matches:
        key = (int(entry["char_start"]), int(entry["char_end"]), entry["normalized_value"])
        if key not in seen:
            seen.add(key)
            unique_matches.append(entry)
    matches = unique_matches

    unique_values = {entry["normalized_value"] for entry in matches}
    if len(unique_values) > 1:
        return {
            "field_name": "project_duration",
            "normalized_value": None,
            "unit": "months",
            "original_text": "; ".join(str(entry["original_text"]) for entry in matches),
            "extraction_method": "duration_normalizer_v2",
            "evidence_coverage": 0.6,
            "validation_warnings": ["Contradictory explicitly labelled project durations found"],
            "status": "clarification_required",
        }

    first = matches[0]
    return {
        "field_name": "project_duration",
        "field_value": str(first["normalized_value"]),
        "normalized_value": first["normalized_value"],
        "unit": "months",
        "original_text": first["original_text"],
        "source_page": _page_for_offset(text, int(first["char_start"])),
        "char_start": first["char_start"],
        "char_end": first["char_end"],
        "extraction_method": "duration_normalizer_v2",
        "evidence_coverage": 1.0,
        "validation_warnings": [],
        "status": "resolved",
    }


def _resolved_field(
    field_name: str,
    normalized_value: str | int | float,
    original_text: str,
    extraction_method: str,
    unit: str | None = None,
    *,
    text: str | None = None,
    char_start: int | None = None,
    status: str = "resolved",
    evidence_coverage: float = 1.0,
) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "field_value": str(normalized_value),
        "normalized_value": normalized_value,
        "unit": unit,
        "original_text": original_text.strip(),
        "source_page": _page_for_offset(text, char_start) if text is not None and char_start is not None else None,
        "section": None,
        "char_start": char_start,
        "char_end": char_start + len(original_text) if char_start is not None else None,
        "extraction_method": extraction_method,
        "evidence_coverage": evidence_coverage,
        "validation_warnings": [],
        "status": status,
    }


def _extract_labeled_value(text: str, labels: list[str]) -> tuple[str, str, int] | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(?P<original>(?:{label_pattern})\s*(?:is|of|:|-)?\s*[*_]*\s*(?P<value>[^\n;]+))",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group("value").strip(), match.group("original").strip(), match.start()


def _normalise_institution(value: str) -> str | None:
    lower_value = value.lower().replace("-", " ")
    if "cmpdi" in lower_value or "coal india" in lower_value or "cil" in lower_value:
        return "psu"
    if "psu" in lower_value or "public sector" in lower_value or "government r&d" in lower_value:
        return "psu"
    if "startup" in lower_value or "start-up" in lower_value or "innovator" in lower_value:
        return "startup"
    if "industry" in lower_value or "company" in lower_value or "private sector" in lower_value:
        return "industry"
    if "research" in lower_value or "institute" in lower_value:
        return "research_institute"
    if "academic" in lower_value or "university" in lower_value or "iit" in lower_value or "nit" in lower_value:
        return "academic"
    return None


def _extract_institution_eligibility(text: str) -> dict[str, Any] | None:
    labeled = _extract_labeled_value(text, ["Institution Type", "Organisation Type", "Applicant Institution", "Lead Institution", "Institution"])
    if labeled:
        value, original, start = labeled
        normalized = _normalise_institution(value)
        if normalized:
            return _resolved_field("institution_eligibility", normalized, original, "keyword_section_heuristic_v2", text=text, char_start=start)
    normalized = _normalise_institution(text)
    if normalized:
        match = re.search(r"cmpdi|coal india|public sector|research institute|university|iit|nit", text, re.IGNORECASE)
        return _resolved_field(
            "institution_eligibility",
            normalized,
            match.group(0) if match else normalized,
            "keyword_section_heuristic_v2",
            text=text,
            char_start=match.start() if match else None,
            evidence_coverage=0.8,
        )
    return None


def _extract_pi_qualification(text: str) -> dict[str, Any] | None:
    labeled = _extract_labeled_value(text, ["PI Qualification", "Principal Investigator Qualification", "Qualification"])
    original = labeled[1] if labeled else ""
    start = labeled[2] if labeled else None
    haystack = labeled[0] if labeled else text
    match = re.search(r"\b(ph\.?\s*d\.?|doctorate|m\.?\s*tech\.?|m\.?\s*sc\.?)\b", haystack, re.IGNORECASE)
    if match:
        value = "phd" if re.search(r"ph|doctorate", match.group(0), re.IGNORECASE) else match.group(0).lower().replace(".", "")
        absolute_start = start if start is not None else match.start()
        return _resolved_field("pi_qualification", value, original or match.group(0), "credential_keyword_heuristic_v2", text=text, char_start=absolute_start)
    return None


def _extract_thrust_area(text: str) -> dict[str, Any] | None:
    patterns = {
        "production-productivity": [
            "production-productivity", "production and productivity",
            "mining productivity", "mechanization", "mechanisation",
        ],
        "safety-health-environment": [
            "safety-health-environment", "safety health environment",
            "safety, health and environment", "mine safety",
        ],
        "waste-to-wealth": [
            "waste-to-wealth", "waste to wealth", "waste utilisation",
            "waste utilization",
        ],
        "alternative-use-clean-coal": [
            "alternative-use-clean-coal", "alternative use of coal",
            "clean coal", "coal gasification", "coal to chemicals",
        ],
        "beneficiation-utilisation": [
            "beneficiation-utilisation", "coal beneficiation",
            "beneficiation", "coal utilisation", "coal utilization",
        ],
        "exploration-innovation-indigenisation": [
            "exploration-innovation-indigenisation",
            "exploration innovation indigenisation",
            "exploration technologies", "indigenisation",
            "indigenization", "import substitution",
        ],
    }

    labeled = _extract_labeled_value(
        text,
        ["Thrust Area", "Focus Area", "Approved Focus Area", "Research Area"],
    )
    search_spaces: list[tuple[str, int, float]] = []
    if labeled:
        value, original, start = labeled
        search_spaces.append((value.lower(), start, 1.0))
    search_spaces.append((text.lower(), 0, 0.8))

    for search_text, offset, coverage in search_spaces:
        candidates: list[tuple[int, str, str]] = []
        for normalized, phrases in patterns.items():
            for phrase in phrases:
                index = search_text.find(phrase)
                if index >= 0:
                    candidates.append((index, normalized, phrase))
        if not candidates:
            continue
        index, normalized, phrase = min(candidates, key=lambda item: item[0])
        absolute_index = offset + index
        return _resolved_field(
            "thrust_area_alignment",
            normalized,
            text[absolute_index : absolute_index + len(phrase)],
            "approved_thrust_area_keyword_match_v3",
            text=text,
            char_start=absolute_index,
            evidence_coverage=coverage,
        )
    return None


def _normalise_yes_no(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.lower()).strip()
    if cleaned in {"no", "none", "nil", "n/a", "na", "not applicable"} or cleaned.startswith("no "):
        return "none"
    if cleaned in {"yes", "present", "included", "proposed"} or cleaned.startswith("yes"):
        return "yes"
    return cleaned


def _extract_optional_policy_field(
    text: str,
    field_name: str,
    labels: list[str],
    extraction_method: str,
) -> dict[str, Any] | None:
    labeled = _extract_labeled_value(text, labels)
    if not labeled:
        return None
    value, original, start = labeled
    return _resolved_field(field_name, _normalise_yes_no(value), original, extraction_method, text=text, char_start=start)


def _extract_prohibited_item(
    text: str,
    field_name: str,
    phrases: list[str],
    extraction_method: str,
) -> dict[str, Any] | None:
    """Resolve prohibited budget/scope items without treating denials as spend.

    Negative statements are evaluated before label-style parsing.  This prevents
    prose such as ``no foreign travel, and ...`` or ``no foreign travel is
    proposed`` from being misread as a positive declaration merely because the
    prohibited phrase is followed by more text on the same line.
    """

    phrase_pattern = "|".join(re.escape(phrase) for phrase in phrases)
    negative_patterns = [
        re.compile(
            rf"(?P<original>(?:no|nil|without)\s+(?:provision\s+for\s+)?(?:{phrase_pattern}))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<original>(?:{phrase_pattern}).{{0,45}}(?:not\s+(?:included|proposed|budgeted|requested|allowed)|no(?:ne)?|nil|zero))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<original>(?:{phrase_pattern}).{{0,35}}(?:prohibited|not\s+permitted))",
            re.IGNORECASE,
        ),
    ]
    for pattern in negative_patterns:
        match = pattern.search(text)
        if match:
            return _resolved_field(
                field_name,
                "none",
                match.group("original"),
                extraction_method,
                text=text,
                char_start=match.start(),
            )

    # Only treat a phrase as a field label when it has an explicit separator or
    # declaration verb.  The generic labeled-value helper intentionally accepts
    # free prose and is therefore too permissive for fail-closed prohibition
    # rules.
    labeled_pattern = re.compile(
        rf"(?P<original>(?:{phrase_pattern})\s*(?::|[-–—]|\bis\b|\bare\b)\s*[*_]*\s*(?P<value>[^\n;]+))",
        re.IGNORECASE,
    )
    labeled_match = labeled_pattern.search(text)
    if labeled_match:
        value = labeled_match.group("value").strip()
        normalized = _normalise_yes_no(value)
        if normalized in {"none", "no", "nil", "n/a", "not applicable"}:
            normalized = "none"
        elif normalized in {"yes", "present", "included", "proposed", "budgeted"}:
            normalized = "yes"
        else:
            normalized = ""
        if normalized:
            return _resolved_field(
                field_name,
                normalized,
                labeled_match.group("original"),
                extraction_method,
                text=text,
                char_start=labeled_match.start(),
            )

    positive_patterns = [
        re.compile(
            rf"(?P<original>(?:{phrase_pattern})\s*(?:is|of|:|-)?\s*(?:yes|included|proposed|requested|budgeted|₹|rs\.?|inr|\d))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<original>(?:budget|cost|funds?).{{0,80}}(?:{phrase_pattern}).{{0,35}}(?:₹|rs\.?|inr|\d+|included|proposed|requested))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<original>(?:purchase|procurement|travel).{{0,40}}(?:{phrase_pattern}))",
            re.IGNORECASE,
        ),
    ]
    for pattern in positive_patterns:
        match = pattern.search(text)
        if match:
            return _resolved_field(
                field_name,
                "yes",
                match.group("original"),
                extraction_method,
                text=text,
                char_start=match.start(),
            )
    return None


def _extract_industry_relevance(text: str) -> dict[str, Any] | None:
    labeled = _extract_labeled_value(
        text,
        [
            "Industry Relevance",
            "Industrial Relevance",
            "Industry Benefit",
            "Coal Industry Benefit",
            "Industry Partner",
            "Industry Demonstration Partner",
            "Demonstration Partner",
        ],
    )
    if labeled:
        value, original, start = labeled
        if re.search(r"\b(?:no|none|not\s+demonstrated|not\s+applicable)\b", value, re.IGNORECASE):
            return _resolved_field(
                "industry_relevance",
                "not_demonstrated",
                original,
                "industry_benefit_evidence_heuristic_v1",
                text=text,
                char_start=start,
            )
        if len(value.split()) >= 4:
            return _resolved_field(
                "industry_relevance",
                "demonstrated",
                original,
                "industry_benefit_evidence_heuristic_v1",
                text=text,
                char_start=start,
                evidence_coverage=0.9,
            )

    industry_signals = [
        "industry deployment plan",
        "industry partner",
        "demonstration partner",
        "technology transfer",
        "field demonstration",
        "deployment feedback",
    ]
    signal_matches = [
        match
        for signal in industry_signals
        if (match := re.search(re.escape(signal), text, re.IGNORECASE)) is not None
    ]
    if len(signal_matches) >= 2:
        first = min(signal_matches, key=lambda item: item.start())
        start = max(0, first.start() - 120)
        end = min(len(text), first.start() + 360)
        return _resolved_field(
            "industry_relevance",
            "demonstrated",
            text[start:end],
            "industry_partnership_signal_heuristic_v2",
            text=text,
            char_start=start,
            evidence_coverage=0.85,
        )

    sentence_pattern = re.compile(
        r"(?P<original>[^.!?\n]{0,160}(?:coal\s+(?:industry|sector|mine|psu)|mine\s+operator|coal\s+company)"
        r"[^.!?\n]{0,160}(?:benefit|adopt|deploy|productivity|safety|cost|saving|commercial|operation)[^.!?\n]{0,100}[.!?]?)",
        re.IGNORECASE,
    )
    match = sentence_pattern.search(text)
    if not match:
        reverse_pattern = re.compile(
            r"(?P<original>[^.!?\n]{0,160}(?:benefit|adopt|deploy|productivity|safety|cost|saving|commercial|operation)"
            r"[^.!?\n]{0,160}(?:coal\s+(?:industry|sector|mine|psu)|mine\s+operator|coal\s+company)[^.!?\n]{0,100}[.!?]?)",
            re.IGNORECASE,
        )
        match = reverse_pattern.search(text)
    if match:
        return _resolved_field(
            "industry_relevance",
            "demonstrated",
            match.group("original"),
            "industry_benefit_evidence_heuristic_v1",
            text=text,
            char_start=match.start(),
            evidence_coverage=0.8,
        )
    return None


def _extract_compliance_readiness(text: str) -> dict[str, Any] | None:
    labeled = _extract_labeled_value(
        text,
        ["Compliance", "Regulatory Compliance", "Safety Compliance", "Environmental Compliance"],
    )
    if labeled:
        value, original, start = labeled
        if re.search(r"\b(?:no|none|not\s+addressed|not\s+applicable)\b", value, re.IGNORECASE):
            return _resolved_field(
                "environmental_safety_compliance",
                "not_addressed",
                original,
                "regulatory_compliance_evidence_heuristic_v1",
                text=text,
                char_start=start,
            )
        if len(value.split()) >= 3:
            return _resolved_field(
                "environmental_safety_compliance",
                "addressed",
                original,
                "regulatory_compliance_evidence_heuristic_v1",
                text=text,
                char_start=start,
                evidence_coverage=0.9,
            )

    pattern = re.compile(
        r"(?P<original>[^.!?\n]{0,180}(?:dgms|environmental|mine\s+safety|statutory|regulatory)"
        r"[^.!?\n]{0,150}(?:comply|compliance|approval|permit|clearance|regulation|standard)[^.!?\n]{0,100}[.!?]?)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        return _resolved_field(
            "environmental_safety_compliance",
            "addressed",
            match.group("original"),
            "regulatory_compliance_evidence_heuristic_v1",
            text=text,
            char_start=match.start(),
            evidence_coverage=0.8,
        )
    return None


def _extract_percentage(text: str, field_name: str, labels: list[str]) -> dict[str, Any] | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    patterns = [
        re.compile(rf"(?P<original>(?:{label_pattern})\s*\(\s*(?P<value>\d+(?:\.\d+)?)\s*%\s*\))", re.IGNORECASE),
        re.compile(rf"(?P<original>(?:{label_pattern})\s*(?:is|of|:|-)?\s*\(?\s*(?P<value>\d+(?:\.\d+)?)\s*%\s*\)?)", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _resolved_field(
                field_name,
                match.group("value"),
                match.group("original"),
                "percentage_pattern_v2",
                "percent",
                text=text,
                char_start=match.start(),
            )
    return None


def _extract_duration_exception(text: str, duration_field: dict[str, Any]) -> dict[str, Any]:
    duration = duration_field.get("normalized_value")
    if isinstance(duration, int | float) and duration <= 24:
        return _resolved_field(
            "duration_exception_above_24",
            "not_required",
            f"Project duration {duration} months does not require an exception",
            "duration_justification_heuristic_v2",
            status="resolved",
        )
    if isinstance(duration, int | float) and duration > 24:
        pattern = re.compile(
            r"(?P<original>(?:duration|period).{0,100}(?:justification|because|due to|requires).{0,220})",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            return _resolved_field(
                "duration_exception_above_24",
                "justification_present",
                match.group("original"),
                "duration_justification_heuristic_v2",
                text=text,
                char_start=match.start(),
                status="resolved",
                evidence_coverage=0.8,
            )
        return {
            "field_name": "duration_exception_above_24",
            "normalized_value": None,
            "original_text": None,
            "extraction_method": "duration_justification_heuristic_v2",
            "evidence_coverage": 0.0,
            "validation_warnings": ["Duration exceeds 24 months but no justification was found"],
            "status": "clarification_required",
        }
    return {
        "field_name": "duration_exception_above_24",
        "normalized_value": None,
        "original_text": None,
        "extraction_method": "duration_justification_heuristic_v2",
        "evidence_coverage": 0.0,
        "validation_warnings": ["Duration must be resolved before exception policy can be applied"],
        "status": "unresolved",
    }


def _extract_duplication(text: str) -> dict[str, Any] | None:
    negative_patterns = [
        r"(?:duplication|duplicate|overlap).{0,50}(?:no|none|not)",
        r"(?:has not been submitted|no prior funding|no previous funding|not submitted to any other funding agency)",
        r"no duplicate equipment",
    ]
    for pattern in negative_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _resolved_field("equipment_duplication", "none", match.group(0), "duplication_declaration_heuristic_v2", text=text, char_start=match.start())
    positive = re.search(r"(?:duplicate|duplication|overlap).{0,100}(?:equipment|project|funding)", text, re.IGNORECASE)
    if positive:
        return _resolved_field(
            "equipment_duplication",
            "possible_duplicate",
            positive.group(0),
            "duplication_declaration_heuristic_v2",
            text=text,
            char_start=positive.start(),
            status="clarification_required",
            evidence_coverage=0.6,
        )
    return None


async def extract_structured_fields(text: str) -> list[dict[str, Any]]:
    """Extract typed structured fields with evidence coordinates."""

    duration = normalize_project_duration(text)
    fields: list[dict[str, Any]] = [duration, _extract_duration_exception(text, duration)]

    for extractor in (_extract_institution_eligibility, _extract_pi_qualification, _extract_thrust_area, _extract_duplication):
        field = extractor(text)
        if field:
            fields.append(field)

    for field_name, labels, method in (
        ("dgms_approval", ["DGMS Approval", "DGMS"], "statutory_approval_keyword_heuristic_v2"),
    ):
        field = _extract_optional_policy_field(text, field_name, labels, method)
        if field:
            fields.append(field)

    for field_name, phrases, method in (
        ("land_purchase", ["land purchase", "purchase of land"], "prohibited_budget_item_heuristic_v1"),
        ("foreign_travel", ["foreign travel", "international travel"], "prohibited_budget_item_heuristic_v1"),
        ("staff_vehicles", ["staff vehicles", "vehicle purchase", "purchase of vehicle", "motor vehicle"], "prohibited_budget_item_heuristic_v1"),
        ("permanent_salary", ["permanent salary", "permanent salaries", "regular staff salary"], "prohibited_budget_item_heuristic_v1"),
        ("routine_academic_study", ["routine academic study", "routine academic research"], "prohibited_scope_heuristic_v1"),
    ):
        field = _extract_prohibited_item(text, field_name, phrases, method)
        if field:
            fields.append(field)

    for extractor in (_extract_industry_relevance, _extract_compliance_readiness):
        field = extractor(text)
        if field:
            fields.append(field)

    contingency = _extract_percentage(text, "contingency_percentage", ["Contingency"])
    overhead = _extract_percentage(text, "overhead_percentage", ["Overhead", "Overheads", "Institutional Overhead", "Institutional Charges"])
    if contingency:
        fields.append(contingency)
    if overhead:
        fields.append(overhead)

    patterns = {
        "trl": [r"(?:current|starting|target)?\s*trl\s*(?:is|of|:|-)?\s*(\d+)"],
        "budget": [r"(?:total|sanction|requested)\s*(?:budget|cost)\s*(?:is|of|:|-)?\s*(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)"],
    }
    for field_name, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields.append(
                    {
                        "field_name": field_name,
                        "field_value": match.group(1),
                        "normalized_value": match.group(1).replace(",", ""),
                        "unit": None,
                        "original_text": match.group(0),
                        "source_page": _page_for_offset(text, match.start()),
                        "char_start": match.start(),
                        "char_end": match.end(),
                        "extraction_method": "keyword_pattern_v2",
                        "evidence_coverage": 1.0,
                        "validation_warnings": [],
                        "status": "resolved",
                    }
                )
                break
    return fields
