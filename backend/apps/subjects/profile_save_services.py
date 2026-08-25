from django.db import transaction

from .models import Subject, SubjectVersion
from .schema_snapshots import derive_product_candidates
from .subject_services import (
    mark_subject_usable_after_save,
    subject_for_user_or_404,
    update_subject_draft,
)
from .version_services import SubjectVersionNoChanges, commit_subject_version


@transaction.atomic
def save_subject_profile(
    *,
    user_id,
    subject_id,
    expected_version: int,
    values: dict,
    profile_values: dict | None,
    request_id,
) -> tuple[Subject, SubjectVersion, bool]:
    """Persist the profile and make its current semantic values effective in one request."""
    subject = update_subject_draft(
        user_id=user_id,
        subject_id=subject_id,
        expected_version=expected_version,
        values=values,
        profile_values=profile_values,
    )
    candidates = derive_product_candidates(subject.schema_snapshot, subject.draft_values)
    confirmations = [
        {
            "candidate_key": candidate["candidate_key"],
            "uniqueness_confirmed": False,
            "include_in_mention": False,
        }
        for candidate in candidates
    ]
    try:
        subject, version = commit_subject_version(
            user_id=user_id,
            subject_id=subject_id,
            expected_version=subject.version,
            product_confirmations=confirmations,
            request_id=request_id,
        )
        subject = mark_subject_usable_after_save(
            user_id=user_id,
            subject_id=subject_id,
            request_id=request_id,
        )
        return subject, version, True
    except SubjectVersionNoChanges:
        subject = subject_for_user_or_404(user=subject.user, subject_id=subject_id)
        if subject.current_version is None:
            raise
        subject = mark_subject_usable_after_save(
            user_id=user_id,
            subject_id=subject_id,
            request_id=request_id,
        )
        return subject, subject.current_version, False
