from dataclasses import asdict

from .models import RiskAction, RiskPolicy
from .risk_catalog import CATALOG_VERSION, RISK_ACTION_CATALOG, mode_is_valid


def synchronize_risk_catalog(*, apply_changes: bool) -> tuple[int, tuple[str, ...]]:
    """Return drift count and unknown keys; preserve valid operator policy choices."""

    catalog_keys = {item.key for item in RISK_ACTION_CATALOG}
    unknown = tuple(
        RiskAction.objects.exclude(key__in=catalog_keys)
        .order_by("key")
        .values_list("key", flat=True)
    )
    changes = len(unknown)
    for definition in RISK_ACTION_CATALOG:
        expected = asdict(definition)
        expected["supported_modes"] = list(definition.supported_modes)
        expected["catalog_version"] = CATALOG_VERSION
        expected["status"] = RiskAction.Status.ACTIVE
        current = RiskAction.objects.filter(pk=definition.key).first()
        action_changed = current is None or any(
            getattr(current, field) != value for field, value in expected.items()
        )
        if action_changed:
            changes += 1
            if apply_changes:
                current, _ = RiskAction.objects.update_or_create(
                    key=definition.key, defaults=expected
                )
        if current is None:
            continue
        policy = RiskPolicy.objects.filter(action=current).first()
        policy_changed = policy is None or not mode_is_valid(definition, policy.current_mode)
        if policy_changed:
            changes += 1
            if apply_changes:
                if policy is None:
                    RiskPolicy.objects.create(action=current, current_mode=definition.default_mode)
                else:
                    policy.current_mode = definition.default_mode
                    policy.version += 1
                    policy.save(update_fields=["current_mode", "version", "updated_at"])
    return changes, unknown
