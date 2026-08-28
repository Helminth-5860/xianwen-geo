from __future__ import annotations

from typing import Any

from apps.images.models import ImageAsset, ImageGenerationJob

from .models import PublishingPreference


_DENSITY_REQUIREMENTS: dict[str, dict[str, int]] = {
    PublishingPreference.ImageDensity.COMPACT: {"cover": 1, "inline": 1, "information": 0},
    PublishingPreference.ImageDensity.STANDARD: {"cover": 1, "inline": 3, "information": 0},
    PublishingPreference.ImageDensity.RICH: {"cover": 1, "inline": 5, "information": 1},
}


def _asset_payload(asset: ImageAsset, *, purpose: str) -> dict[str, Any]:
    return {
        "asset_id": str(asset.id),
        "purpose": purpose,
        "source_type": asset.source_type,
        "role": asset.role,
        "width": asset.width,
        "height": asset.height,
        "mime_type": asset.mime_type,
        "is_customer_real_asset": asset.source_type == ImageAsset.SourceType.UPLOADED,
    }


def _take_assets(candidates: list[ImageAsset], *, role: str, count: int, used: set[str]) -> list[ImageAsset]:
    selected: list[ImageAsset] = []
    for asset in candidates:
        if str(asset.id) in used:
            continue
        if role == "cover" and asset.role not in {ImageGenerationJob.Role.COVER, ImageGenerationJob.Role.CHANNEL}:
            continue
        if role in {"inline", "information"} and asset.role not in {
            ImageGenerationJob.Role.ILLUSTRATION,
            ImageGenerationJob.Role.CHANNEL,
        }:
            continue
        selected.append(asset)
        used.add(str(asset.id))
        if len(selected) >= count:
            break
    return selected


def build_image_plan(*, user, subject, article, strategy: str, density: str) -> dict[str, Any]:
    requirements = dict(_DENSITY_REQUIREMENTS.get(density) or _DENSITY_REQUIREMENTS[PublishingPreference.ImageDensity.STANDARD])
    queryset = ImageAsset.objects.filter(
        user=user,
        subject=subject,
        lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
        moderation_status=ImageAsset.ModerationStatus.APPROVED,
    ).filter(article=article) | ImageAsset.objects.filter(
        user=user,
        subject=subject,
        lifecycle_status=ImageAsset.LifecycleStatus.ACTIVE,
        moderation_status=ImageAsset.ModerationStatus.APPROVED,
        is_subject_library=True,
    )
    candidates = list(queryset.distinct().order_by("-created_at", "-id")[:80])

    # 客户真实素材永远排在 AI 生成素材之前；“仅企业素材”模式直接排除生成图。
    candidates.sort(
        key=lambda item: (
            0 if item.source_type == ImageAsset.SourceType.UPLOADED else 1,
            0 if item.article_id == article.id else 1,
            -int(item.created_at.timestamp()),
        )
    )
    if strategy == PublishingPreference.ImageStrategy.CUSTOMER_ONLY:
        candidates = [item for item in candidates if item.source_type == ImageAsset.SourceType.UPLOADED]

    used: set[str] = set()
    selected: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for purpose in ("cover", "inline", "information"):
        needed = requirements[purpose]
        assets = _take_assets(candidates, role=purpose, count=needed, used=used)
        selected.extend(_asset_payload(asset, purpose=purpose) for asset in assets)
        shortage = max(0, needed - len(assets))
        if shortage:
            missing.append(
                {
                    "purpose": purpose,
                    "count": shortage,
                    "ai_generation_allowed": strategy != PublishingPreference.ImageStrategy.CUSTOMER_ONLY,
                    "truth_constraint": (
                        "只能生成概念视觉、封面背景、流程/信息图；不得生成并冒充企业真实团队、工厂、产品实物、案例现场或资质证书"
                    ),
                }
            )

    return {
        "strategy": strategy,
        "density": density,
        "requirements": requirements,
        "selected_assets": selected,
        "missing_assets": missing,
        "customer_assets_first": strategy != PublishingPreference.ImageStrategy.AI_AUTO,
        "allow_ai_supplement": strategy != PublishingPreference.ImageStrategy.CUSTOMER_ONLY,
        "status": "ready" if not missing else "needs_supplement",
    }
