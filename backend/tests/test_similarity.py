from app.services.similarity import proposal_text_similarity


def test_identical_proposals_have_full_similarity():
    text = "Coal mine safety research methodology with field validation and deployment plan. " * 12
    assert proposal_text_similarity(text, text) == 1.0


def test_shared_keywords_do_not_create_duplicate_flag():
    left = "Coal mine safety research methodology with sensors and field validation. " * 8
    right = "Coal beneficiation pilot budget commercialisation and ash reduction. " * 8
    assert proposal_text_similarity(left, right) < 0.25


def test_reworded_overlap_is_advisory_not_exact():
    left = "Advanced dry coal beneficiation system for washery rejects with pilot validation. " * 10
    right = "Advanced dry coal beneficiation system for washery rejects with field validation. " * 10
    score = proposal_text_similarity(left, right)
    assert 0.45 < score < 1.0
