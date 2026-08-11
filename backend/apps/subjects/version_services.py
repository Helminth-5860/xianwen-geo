import copy
from typing import Any

from django.db import transaction
from rest_framework.exceptions import NotFound

from apps.users.models import User

from .models import Subject, SubjectEvent, SubjectName, SubjectProduct, SubjectVersion
from .schema_snapshots import (
    FrozenRequiredFieldsError,
    FrozenSemanticError,
    assert_snapshot_integrity,
    committed_semantic_digest,
    derive_frozen_semantics,
    validate_frozen_commit_values,
    values_digest,
)
from .subject_services import (
    SubjectAccountReadOnly,
    SubjectBusinessError,
    SubjectEntitlementIntegrityError,
    SubjectStateConflict,
    SubjectVersionConflict,
    _ensure_subject_write_allowed,
    subject_for_user_or_404,
)


class SubjectRequiredFieldsIncomplete(SubjectBusinessError):
    code = "SUBJECT_REQUIRED_FIELDS_INCOMPLETE"

    def __init__(self, field_keys: list[str]):
        self.field_keys = field_keys
        super().__init__(",".join(field_keys))


class SubjectSemanticsInvalid(SubjectBusinessError):
    code = "SUBJECT_SEMANTICS_INVALID"


class SubjectProductConfirmationInvalid(SubjectBusinessError):
    code = "SUBJECT_PRODUCT_CONFIRMATION_INVALID"


class SubjectVersionNoChanges(SubjectBusinessError):
    code = "SUBJECT_VERSION_NO_CHANGES"


def subject_versions_for_user(*, user: User, subject_id):
    if not Subject.objects.filter(pk=subject_id, user=user).exists():
        raise NotFound
    return (
        SubjectVersion.objects.filter(subject_id=subject_id)
        .prefetch_related("names", "products")
        .order_by("-version_no", "id")
    )


def subject_version_for_user_or_404(*, user: User, subject_id, version_id) -> SubjectVersion:
    try:
        return (
            SubjectVersion.objects.filter(subject_id=subject_id, subject__user=user)
            .prefetch_related("names", "products")
            .get(pk=version_id)
        )
    except SubjectVersion.DoesNotExist as exc:
        raise NotFound from exc


def _validated_confirmations(
    candidates: list[dict[str, str]], confirmations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidate_by_key = {item["candidate_key"]: item for item in candidates}
    supplied_keys = [item["candidate_key"] for item in confirmations]
    if len(supplied_keys) != len(set(supplied_keys)) or set(supplied_keys) != set(candidate_by_key):
        raise SubjectProductConfirmationInvalid
    normalized: list[dict[str, Any]] = []
    for confirmation in confirmations:
        if confirmation["include_in_mention"] and not confirmation["uniqueness_confirmed"]:
            raise SubjectProductConfirmationInvalid
        normalized.append(
            {
                "candidate_key": confirmation["candidate_key"],
                "uniqueness_confirmed": confirmation["uniqueness_confirmed"],
                "include_in_mention": confirmation["include_in_mention"],
            }
        )
    return sorted(normalized, key=lambda item: item["candidate_key"])


@transaction.atomic
def commit_subject_version(
    *,
    user_id,
    subject_id,
    expected_version: int,
    product_confirmations: list[dict[str, Any]],
    request_id,
) -> tuple[Subject, SubjectVersion]:
    user = User.objects.select_for_update().get(pk=user_id)
    _ensure_subject_write_allowed(user)
    subject = subject_for_user_or_404(user=user, subject_id=subject_id, lock=True)
    if subject.version != expected_version:
        raise SubjectVersionConflict
    if subject.status == Subject.Status.ARCHIVED:
        raise SubjectStateConflict

    try:
        assert_snapshot_integrity(subject.schema_snapshot, subject.schema_digest)
        field_values = validate_frozen_commit_values(
            subject.schema_snapshot,
            copy.deepcopy(subject.draft_values),
        )
        names, candidates = derive_frozen_semantics(subject.schema_snapshot, field_values)
    except FrozenRequiredFieldsError as exc:
        raise SubjectRequiredFieldsIncomplete(exc.field_keys) from exc
    except FrozenSemanticError as exc:
        raise SubjectSemanticsInvalid from exc
    except ValueError as exc:
        raise SubjectEntitlementIntegrityError from exc

    confirmations = _validated_confirmations(candidates, product_confirmations)
    confirmation_by_key = {item["candidate_key"]: item for item in confirmations}
    field_digest = values_digest(field_values)
    semantic_digest = committed_semantic_digest(
        schema_digest_value=subject.schema_digest,
        field_values=field_values,
        product_confirmations=confirmations,
    )
    current = subject.current_version
    if current is not None and current.semantic_digest == semantic_digest:
        raise SubjectVersionNoChanges
    next_version_no = 1 if current is None else current.version_no + 1
    official_name = next(
        name["display_value"] for name in names if name["role"] == SubjectName.Role.OFFICIAL_NAME
    )
    version = SubjectVersion.objects.create(
        subject=subject,
        version_no=next_version_no,
        field_values=field_values,
        schema_version=subject.schema_version,
        schema_snapshot_format_version=subject.schema_snapshot_format_version,
        schema_snapshot=copy.deepcopy(subject.schema_snapshot),
        schema_digest=subject.schema_digest,
        field_values_digest=field_digest,
        semantic_digest=semantic_digest,
        official_name=official_name,
        created_by=user,
    )
    SubjectName.objects.bulk_create(
        [SubjectName(subject_version=version, **name) for name in names]
    )
    SubjectProduct.objects.bulk_create(
        [
            SubjectProduct(
                subject_version=version,
                **candidate,
                uniqueness_confirmed=confirmation_by_key[candidate["candidate_key"]][
                    "uniqueness_confirmed"
                ],
                include_in_mention=confirmation_by_key[candidate["candidate_key"]][
                    "include_in_mention"
                ],
            )
            for candidate in candidates
        ]
    )
    subject.current_version = version
    subject.retest_required = current is not None
    subject.version += 1
    subject.save(update_fields=["current_version", "retest_required", "version", "updated_at"])
    SubjectEvent.objects.create(
        subject=subject,
        subject_version=version,
        event_type=SubjectEvent.EventType.VERSION_COMMITTED,
        from_status=subject.status,
        to_status=subject.status,
        safe_summary={"version_no": version.version_no},
        actor=user,
        request_id=request_id,
    )
    return subject, version


__all__ = [
    "SubjectAccountReadOnly",
    "SubjectProductConfirmationInvalid",
    "SubjectRequiredFieldsIncomplete",
    "SubjectSemanticsInvalid",
    "SubjectVersionNoChanges",
    "commit_subject_version",
    "subject_version_for_user_or_404",
    "subject_versions_for_user",
]
