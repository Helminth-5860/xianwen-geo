from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from apps.questions.bank_models import QuestionFields

from .models import (
    ModelResponse,
    ModelResponseCitation,
    ProgrammaticScoreResult,
)

_EXPLICIT_RANK_PATTERNS = (
    re.compile(r"^\s*第\s*(\d{1,3})\s*名"),
    re.compile(r"^\s*#\s*(\d{1,3})(?:\s|$)"),
    re.compile(r"^\s*(\d{1,3})\s*[.)、．:：-]\s*"),
)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class MatchCandidate:
    kind: str
    display_value: str
    matching_value: str
    priority: int


@dataclass(frozen=True)
class MentionMatch:
    kind: str
    display_value: str
    matching_value: str
    start: int


@dataclass(frozen=True)
class RankResult:
    position: int | None
    score: int | None
    resolution: str


def _candidate_pattern(matching_value: str) -> re.Pattern[str]:
    escaped = re.escape(matching_value)
    if _CJK_RE.search(matching_value):
        return re.compile(escaped)
    return re.compile(rf"(?<!\w){escaped}(?!\w)")


def _normalized(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def find_subject_mention(
    raw_text: str,
    candidates: tuple[MatchCandidate, ...],
) -> MentionMatch | None:
    normalized_text = _normalized(raw_text)
    matches: list[MentionMatch] = []
    for candidate in candidates:
        if not candidate.matching_value:
            continue
        match = _candidate_pattern(candidate.matching_value).search(normalized_text)
        if match is None:
            continue
        matches.append(
            MentionMatch(
                kind=candidate.kind,
                display_value=candidate.display_value,
                matching_value=candidate.matching_value,
                start=match.start(),
            )
        )
    if not matches:
        return None

    priority = {candidate.kind: candidate.priority for candidate in candidates}
    return min(
        matches, key=lambda item: (item.start, priority.get(item.kind, 99), item.display_value)
    )


def rank_score(position: int) -> int:
    if position <= 1:
        return 100
    if position <= 3:
        return 80
    if position <= 5:
        return 60
    if position <= 10:
        return 40
    return 20


def deterministic_rank(raw_text: str, mention: MentionMatch | None) -> RankResult:
    if mention is None:
        return RankResult(
            position=None,
            score=0,
            resolution=ProgrammaticScoreResult.RankResolution.DETERMINISTIC,
        )

    pattern = _candidate_pattern(mention.matching_value)
    for line in raw_text.splitlines():
        normalized_line = _normalized(line)
        if pattern.search(normalized_line) is None:
            continue
        for rank_pattern in _EXPLICIT_RANK_PATTERNS:
            rank_match = rank_pattern.match(line)
            if rank_match is None:
                continue
            position = int(rank_match.group(1))
            if position < 1:
                continue
            return RankResult(
                position=position,
                score=rank_score(position),
                resolution=ProgrammaticScoreResult.RankResolution.DETERMINISTIC,
            )
        return RankResult(
            position=None,
            score=None,
            resolution=ProgrammaticScoreResult.RankResolution.SEMANTIC_REQUIRED,
        )

    return RankResult(
        position=None,
        score=None,
        resolution=ProgrammaticScoreResult.RankResolution.SEMANTIC_REQUIRED,
    )


def citation_base(
    citations: tuple[ModelResponseCitation, ...],
) -> tuple[int | None, str, int]:
    if not citations:
        return (
            0,
            ProgrammaticScoreResult.CitationResolution.DETERMINISTIC,
            0,
        )

    if any(citation.url_status == ModelResponseCitation.UrlStatus.SAFE for citation in citations):
        return (
            None,
            ProgrammaticScoreResult.CitationResolution.SEMANTIC_REQUIRED,
            len(citations),
        )

    if any(
        citation.url_status == ModelResponseCitation.UrlStatus.UNRESOLVED
        or (
            citation.url_status == ModelResponseCitation.UrlStatus.MISSING
            and bool(citation.source_name)
        )
        for citation in citations
    ):
        return (
            20,
            ProgrammaticScoreResult.CitationResolution.DETERMINISTIC,
            len(citations),
        )

    # Invalid/blocked-only evidence is not rewarded. This prevents unsafe or
    # malformed URLs from earning the documented "unverifiable source" floor.
    return (
        0,
        ProgrammaticScoreResult.CitationResolution.DETERMINISTIC,
        len(citations),
    )


def _candidates_for_response(model_response: ModelResponse) -> tuple[MatchCandidate, ...]:
    subject_version = model_response.model_call.job.snapshot.subject_version
    candidates: list[MatchCandidate] = []
    priorities = {
        "official_name": 0,
        "alias": 1,
        "english_name": 2,
        "product": 3,
    }

    for name in subject_version.names.all():
        candidates.append(
            MatchCandidate(
                kind=name.role,
                display_value=name.display_value,
                matching_value=name.matching_value,
                priority=priorities.get(name.role, 9),
            )
        )

    for product in subject_version.products.filter(include_in_mention=True):
        candidates.append(
            MatchCandidate(
                kind="product",
                display_value=product.display_value,
                matching_value=product.matching_value,
                priority=priorities["product"],
            )
        )

    return tuple(candidates)


def score_programmatic_response(
    *,
    model_response: ModelResponse,
) -> ProgrammaticScoreResult | None:
    response = (
        ModelResponse.objects.select_related(
            "model_call__job__snapshot__subject_version",
            "model_call__question_snapshot",
        )
        .prefetch_related(
            "model_call__job__snapshot__subject_version__names",
            "model_call__job__snapshot__subject_version__products",
            "citations",
        )
        .get(pk=model_response.pk)
    )
    question = response.model_call.question_snapshot
    if not question.participates_in_scoring:
        return None

    citation_rows = tuple(response.citations.all())
    citation_score, citation_resolution, citation_count = citation_base(citation_rows)

    if question.question_type == QuestionFields.QuestionType.BRAND_DIRECTED:
        return ProgrammaticScoreResult.objects.create(
            model_response=response,
            scoring_rule_version=response.model_call.job.snapshot.scoring_rule_version,
            question_type=question.question_type,
            mention_score=None,
            matched_kind="",
            matched_value="",
            rank_position=None,
            rank_score=None,
            rank_resolution=ProgrammaticScoreResult.RankResolution.NOT_APPLICABLE,
            citation_base_score=citation_score,
            citation_resolution=citation_resolution,
            citation_evidence_count=citation_count,
            evidence={
                "mention": "not_applicable",
                "rank": "not_applicable",
                "citation_evidence_count": citation_count,
            },
        )

    candidates = _candidates_for_response(response)
    mention = find_subject_mention(response.raw_text, candidates)
    mention_score = 100 if mention is not None else 0
    rank = deterministic_rank(response.raw_text, mention)

    return ProgrammaticScoreResult.objects.create(
        model_response=response,
        scoring_rule_version=response.model_call.job.snapshot.scoring_rule_version,
        question_type=question.question_type,
        mention_score=mention_score,
        matched_kind=mention.kind if mention else "",
        matched_value=mention.display_value if mention else "",
        rank_position=rank.position,
        rank_score=rank.score,
        rank_resolution=rank.resolution,
        citation_base_score=citation_score,
        citation_resolution=citation_resolution,
        citation_evidence_count=citation_count,
        evidence={
            "matched_kind": mention.kind if mention else "",
            "matched_value": mention.display_value if mention else "",
            "rank_position": rank.position,
            "rank_resolution": rank.resolution,
            "citation_evidence_count": citation_count,
        },
    )
