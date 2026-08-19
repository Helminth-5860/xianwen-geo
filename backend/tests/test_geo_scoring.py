from __future__ import annotations

from apps.geo.models import ModelResponseCitation, ProgrammaticScoreResult
from apps.geo.scoring import (
    MatchCandidate,
    citation_base,
    deterministic_rank,
    find_subject_mention,
    rank_score,
)


def test_official_alias_and_unique_product_matching_is_explicit_only():
    candidates = (
        MatchCandidate("official_name", "ACME Corp", "acme corp", 0),
        MatchCandidate("alias", "ACME", "acme", 1),
        MatchCandidate("product", "Product One", "product one", 3),
    )

    match = find_subject_mention("I recommend ACME Corp for this use.", candidates)

    assert match is not None
    assert match.kind == "official_name"
    assert match.display_value == "ACME Corp"


def test_latin_matching_does_not_accept_embedded_token():
    candidates = (MatchCandidate("alias", "ACME", "acme", 1),)

    assert find_subject_mention("The product is ACME2.", candidates) is None


def test_explicit_rank_mapping():
    candidates = (MatchCandidate("official_name", "ACME Corp", "acme corp", 0),)
    mention = find_subject_mention("2. ACME Corp\n3. Other", candidates)

    result = deterministic_rank("2. ACME Corp\n3. Other", mention)

    assert result.position == 2
    assert result.score == 80
    assert result.resolution == ProgrammaticScoreResult.RankResolution.DETERMINISTIC
    assert rank_score(1) == 100
    assert rank_score(4) == 60
    assert rank_score(8) == 40
    assert rank_score(11) == 20


def test_unstructured_rank_is_deferred_to_semantic_scoring():
    candidates = (MatchCandidate("official_name", "ACME Corp", "acme corp", 0),)
    text = "ACME Corp is worth considering for several reasons."
    mention = find_subject_mention(text, candidates)

    result = deterministic_rank(text, mention)

    assert result.position is None
    assert result.score is None
    assert result.resolution == ProgrammaticScoreResult.RankResolution.SEMANTIC_REQUIRED


def test_no_mention_has_zero_deterministic_rank():
    result = deterministic_rank("No matching subject.", None)

    assert result.position is None
    assert result.score == 0
    assert result.resolution == ProgrammaticScoreResult.RankResolution.DETERMINISTIC


def test_citation_base_is_zero_without_evidence():
    score, resolution, count = citation_base(())

    assert score == 0
    assert resolution == ProgrammaticScoreResult.CitationResolution.DETERMINISTIC
    assert count == 0


def test_blocked_only_citation_does_not_earn_unverifiable_source_floor():
    citation = ModelResponseCitation(
        sort_order=0,
        url_status=ModelResponseCitation.UrlStatus.BLOCKED,
        extraction_method=ModelResponseCitation.ExtractionMethod.RAW_TEXT,
    )

    score, resolution, count = citation_base((citation,))

    assert score == 0
    assert resolution == ProgrammaticScoreResult.CitationResolution.DETERMINISTIC
    assert count == 1


def test_unresolved_citation_uses_documented_unverifiable_source_floor():
    citation = ModelResponseCitation(
        sort_order=0,
        source_name="Known source",
        url_status=ModelResponseCitation.UrlStatus.UNRESOLVED,
        extraction_method=ModelResponseCitation.ExtractionMethod.PROVIDER,
    )

    score, resolution, count = citation_base((citation,))

    assert score == 20
    assert resolution == ProgrammaticScoreResult.CitationResolution.DETERMINISTIC
    assert count == 1
