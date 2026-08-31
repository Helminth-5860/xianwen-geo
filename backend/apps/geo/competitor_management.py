from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import NotFound as DRFNotFound

from apps.core.error_codes import ErrorCode
from apps.keywords.normalization import KeywordNormalizationError, normalize_plain_text
from apps.search_discovery.normalization import normalize_url
from apps.search_discovery.subject_context import extract_self_domains
from apps.subjects.models import Subject, SubjectVersion
from apps.subjects.subject_services import subject_for_user_or_404

from .models import SubjectCompetitor

MAX_SUBJECT_COMPETITORS = 3
_WEBSITE_VALIDATOR = URLValidator(schemes=("http", "https"))


@dataclass(frozen=True)
class CompetitorBusinessError(Exception):
    code: ErrorCode
    status: int


def subject_for_competitors(*, user, subject_id, lock: bool = False) -> Subject:
    try:
        subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=lock)
    except DRFNotFound as exc:
        raise Http404 from exc
    if subject.status != Subject.Status.ACTIVE or subject.current_version_id is None:
        raise Http404
    return subject


def subject_version_for_competitors(*, subject: Subject) -> SubjectVersion:
    version = subject.current_version
    if version is None:
        raise Http404
    return version


def active_competitors(*, subject: Subject):
    return SubjectCompetitor.objects.filter(
        tenant_id=subject.tenant_id,
        subject=subject,
        status=SubjectCompetitor.Status.ACTIVE,
    ).order_by("position", "created_at", "id")


def competitor_for_user(
    *, user, subject: Subject, competitor_id, lock: bool = False
) -> SubjectCompetitor:
    query = active_competitors(subject=subject).filter(pk=competitor_id)
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        return query.get()
    except SubjectCompetitor.DoesNotExist as exc:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_NOT_FOUND, 404) from exc


def _normalized_name(value: str) -> tuple[str, str]:
    try:
        return normalize_plain_text(value, max_length=255)
    except (KeywordNormalizationError, TypeError) as exc:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422) from exc


def _normalized_website(value: str) -> tuple[str, str]:
    raw = value.strip()
    if not raw:
        return "", ""
    if len(raw) > 500:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422)
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
    except ValueError as exc:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422) from exc
    if parsed.username is not None or parsed.password is not None:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422)
    try:
        _WEBSITE_VALIDATOR(candidate)
    except ValidationError as exc:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422) from exc
    try:
        normalized = normalize_url(candidate)
    except ValueError as exc:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422) from exc
    if normalized is None:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422)
    normalized_url, _host, root = normalized
    if len(normalized_url) > 500 or len(root) > 255 or not root or "." not in root:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VALUES_INVALID, 422)
    return normalized_url, root


def _assert_not_subject(*, subject: Subject, name_key: str, website_domain: str) -> None:
    version = subject_version_for_competitors(subject=subject)
    name_keys = {normalize_plain_text(version.official_name, max_length=500)[1]}
    name_keys.update(version.names.values_list("matching_value", flat=True))
    if name_key in name_keys:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_IS_SUBJECT, 409)
    if website_domain:
        self_domains = extract_self_domains(version.field_values)
        if website_domain in self_domains:
            raise CompetitorBusinessError(ErrorCode.COMPETITOR_IS_SUBJECT, 409)


def _assert_not_duplicate(
    *, user, subject: Subject, name_key: str, website_domain: str, exclude_id=None
) -> None:
    query = active_competitors(subject=subject)
    if exclude_id is not None:
        query = query.exclude(pk=exclude_id)
    if query.filter(normalized_name=name_key).exists():
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_DUPLICATE, 409)
    if website_domain and query.filter(website_domain=website_domain).exists():
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_DUPLICATE, 409)


def competitor_payload(competitor: SubjectCompetitor) -> dict[str, object]:
    return {
        "id": str(competitor.pk),
        "name": competitor.name,
        "website": competitor.website,
        "domain": competitor.website_domain,
        "source": competitor.source,
        "position": competitor.position,
        "version": competitor.version,
        "created_at": competitor.created_at,
        "updated_at": competitor.updated_at,
    }


def competitor_list_payload(*, user, subject_id) -> dict[str, object]:
    subject = subject_for_competitors(user=user, subject_id=subject_id)
    version = subject_version_for_competitors(subject=subject)
    items = tuple(active_competitors(subject=subject))
    return {
        "subject": {
            "id": str(subject.pk),
            "name": version.official_name,
        },
        "items": [competitor_payload(item) for item in items],
        "count": len(items),
        "max_count": MAX_SUBJECT_COMPETITORS,
    }


@transaction.atomic
def create_competitor(*, user, subject_id, name: str, website: str) -> SubjectCompetitor:
    subject = subject_for_competitors(user=user, subject_id=subject_id, lock=True)
    display_name, name_key = _normalized_name(name)
    normalized_website, website_domain = _normalized_website(website)
    _assert_not_subject(
        subject=subject,
        name_key=name_key,
        website_domain=website_domain,
    )
    current = tuple(active_competitors(subject=subject))
    if len(current) >= MAX_SUBJECT_COMPETITORS:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_LIMIT_REACHED, 409)
    _assert_not_duplicate(
        user=user,
        subject=subject,
        name_key=name_key,
        website_domain=website_domain,
    )
    occupied_positions = {item.position for item in current}
    position = next(
        candidate
        for candidate in range(1, MAX_SUBJECT_COMPETITORS + 1)
        if candidate not in occupied_positions
    )
    return SubjectCompetitor.objects.create(
        user=user,
        tenant_id=subject.tenant_id,
        subject=subject,
        name=display_name,
        normalized_name=name_key,
        website=normalized_website,
        website_domain=website_domain,
        source=SubjectCompetitor.Source.MANUAL,
        position=position,
    )


@transaction.atomic
def update_competitor(
    *,
    user,
    subject_id,
    competitor_id,
    name: str | None,
    website: str | None,
    expected_version: int,
) -> SubjectCompetitor:
    subject = subject_for_competitors(user=user, subject_id=subject_id, lock=True)
    competitor = competitor_for_user(
        user=user,
        subject=subject,
        competitor_id=competitor_id,
        lock=True,
    )
    if competitor.version != expected_version:
        raise CompetitorBusinessError(ErrorCode.COMPETITOR_VERSION_CONFLICT, 409)
    display_name, name_key = _normalized_name(name if name is not None else competitor.name)
    normalized_website, website_domain = _normalized_website(
        website if website is not None else competitor.website
    )
    _assert_not_subject(
        subject=subject,
        name_key=name_key,
        website_domain=website_domain,
    )
    _assert_not_duplicate(
        user=user,
        subject=subject,
        name_key=name_key,
        website_domain=website_domain,
        exclude_id=competitor.pk,
    )
    competitor.name = display_name
    competitor.normalized_name = name_key
    competitor.website = normalized_website
    competitor.website_domain = website_domain
    competitor.version += 1
    competitor.save(
        update_fields=(
            "name",
            "normalized_name",
            "website",
            "website_domain",
            "version",
            "updated_at",
        )
    )
    return competitor


@transaction.atomic
def remove_competitor(*, user, subject_id, competitor_id) -> None:
    subject = subject_for_competitors(user=user, subject_id=subject_id, lock=True)
    competitor = competitor_for_user(
        user=user,
        subject=subject,
        competitor_id=competitor_id,
        lock=True,
    )
    competitor.status = SubjectCompetitor.Status.REMOVED
    competitor.removed_at = timezone.now()
    competitor.version += 1
    competitor.save(update_fields=("status", "removed_at", "version", "updated_at"))

    remaining = tuple(active_competitors(subject=subject))
    for position, item in enumerate(remaining, start=1):
        if item.position == position:
            continue
        item.position = position
        item.version += 1
        item.save(update_fields=("position", "version", "updated_at"))
