from __future__ import annotations

import copy
from typing import Any

from apps.subjects.models import SubjectVersion


def subject_version_ai_facts(version: SubjectVersion) -> dict[str, Any]:
    fields = version.schema_snapshot.get("fields", [])
    allowed = {
        row.get("field_key")
        for row in fields
        if isinstance(row, dict) and row.get("used_for_ai") is True
    }
    values = {
        key: copy.deepcopy(value) for key, value in version.field_values.items() if key in allowed
    }
    return {
        "subject_id": str(version.subject_id),
        "subject_version_id": str(version.pk),
        "official_name": version.official_name,
        "fields": values,
        "names": [
            {"role": row.role, "value": row.display_value}
            for row in version.names.order_by("role", "display_value", "id")
        ],
        "products": [
            {
                "value": row.display_value,
                "uniqueness_confirmed": row.uniqueness_confirmed,
                "include_in_mention": row.include_in_mention,
            }
            for row in version.products.order_by("display_value", "id")
        ],
    }
