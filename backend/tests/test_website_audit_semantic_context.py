from apps.website_audits.semantic_context import _public_subject_fields, _safe_scalar


def test_public_subject_fields_exclude_sensitive_contact_and_secret_values():
    values = {
        "official_name": "显问",
        "brand_name": "显问 AI",
        "primary_business": "GEO 搜索可见度检测",
        "contact_phone": "13800000000",
        "business_address": "某地址",
        "api_secret": "do-not-send",
        "unrelated_internal_flag": "internal",
    }
    assert _public_subject_fields(values) == {
        "official_name": "显问",
        "brand_name": "显问 AI",
        "primary_business": "GEO 搜索可见度检测",
    }


def test_safe_scalar_removes_nested_sensitive_keys_and_bounds_lists():
    value = {
        "website": "https://example.com",
        "contact_phone": "13800000000",
        "channels": ["公众号", "官网"],
    }
    assert _safe_scalar(value) == {
        "website": "https://example.com",
        "channels": ["公众号", "官网"],
    }
