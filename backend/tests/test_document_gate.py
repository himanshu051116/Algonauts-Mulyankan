"""Document-role and proposal acceptance gate regression tests."""

from app.services.document_gate import assess_document, gate_only_scoring_result
from backend.tests.test_brochure_ml import STRONG_PROPOSAL


def test_valid_coal_proposal_is_accepted():
    gate = assess_document(STRONG_PROPOSAL, "MOC-ST", file_name="proposal.pdf")
    assert gate.status == "accepted"
    assert gate.accepted is True
    assert gate.classified_role == "main_proposal"


def test_standalone_resume_is_rejected_without_score():
    resume = """
    Curriculum Vitae Resume. Education: B.Tech with CGPA. Technical skills include Python,
    machine learning, interfaces and environmental analytics. Work experience includes an
    internship and software projects. GitHub, LinkedIn and LeetCode profiles are listed.
    Awards, certifications, publications and relationship milestones are described. This
    document is a résumé and contains no authoritative proposal budget or implementation plan.
    """
    gate = assess_document(resume, "MOC-ST", file_name="candidate-resume.pdf")
    assert gate.status == "invalid_document"
    assert gate.document_type == "resume"
    result = gate_only_scoring_result(gate)
    assert result["total_score"] is None
    assert result["diagnostic_score"] is None
    assert result["model_invoked"] is False


def test_supporting_document_cannot_initiate_scoring():
    gate = assess_document(
        STRONG_PROPOSAL,
        "MOC-ST",
        declared_role="pi_cv",
        file_name="pi-cv.pdf",
    )
    assert gate.status == "role_disallowed"
    assert gate.scoring_allowed is False


def test_reference_brochure_is_not_applicant_evidence():
    brochure = ("Purpose of this brochure. Who can apply? Applicant guidance. "
                "What applicants should do. Marking summary table. " * 20)
    gate = assess_document(brochure, "MOC-ST", file_name="guidance-brochure.pdf")
    assert gate.status == "invalid_document"
    assert gate.document_type == "reference_guideline"


def test_ambiguous_proposal_is_sent_to_manual_review_not_rejected():
    text = (
        "Project objectives and methodology are described. "
        "A work plan and budget will be submitted after consultation. "
        "The proposal concerns a general educational technology pilot. " * 8
    )
    gate = assess_document(text, "MOC-ST", file_name="proposal.pdf")
    assert gate.status == "manual_review"
    assert gate.accepted is False
    assert gate.scoring_allowed is False


def test_low_structure_non_resume_is_sent_to_manual_review():
    text = (
        "This technical concept describes a coal mine monitoring pilot and associated research. "
        "It includes background narrative but uses no standard proposal headings. " * 12
    )
    gate = assess_document(text, "MOC-ST", file_name="concept-note.pdf")
    assert gate.status == "manual_review"
    assert gate.accepted is False
