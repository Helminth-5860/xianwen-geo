import pytest

from apps.websites.serializers import WebsiteGenerateSerializer
from apps.websites.services import WebsiteSchemaError, normalize_site_output


def _page(key: str, title: str):
    return {
        "key": key,
        "title": title,
        "seo_title": f"{title} SEO",
        "seo_description": f"{title}页面说明",
        "sections": [
            {
                "type": "hero" if key == "home" else "text",
                "title": title,
                "body": f"{title}正文",
                "items": [],
            }
        ],
    }


def _site():
    return {
        "tagline": "让企业信息更容易被理解",
        "pages": [
            _page("home", "首页"),
            _page("about", "关于我们"),
            _page("services", "产品服务"),
            _page("solutions", "解决方案"),
            _page("faq", "常见问题"),
            _page("contact", "联系我们"),
        ],
    }


def test_normalize_site_output_builds_fixed_page_slugs():
    normalized = normalize_site_output(_site())

    assert normalized["schema_version"] == 1
    assert [page["key"] for page in normalized["pages"]] == [
        "home",
        "about",
        "services",
        "solutions",
        "faq",
        "contact",
    ]
    assert [page["slug"] for page in normalized["pages"]] == [
        "",
        "about",
        "services",
        "solutions",
        "faq",
        "contact",
    ]


def test_normalize_site_output_rejects_unexpected_model_fields():
    value = _site()
    value["pages"][0]["internal_note"] = "不应进入官网数据"

    with pytest.raises(WebsiteSchemaError):
        normalize_site_output(value)


def test_generate_serializer_limits_combined_image_materials():
    serializer = WebsiteGenerateSerializer(
        data={
            "style_key": "professional",
            "image_asset_ids": [f"00000000-0000-0000-0000-{index:012d}" for index in range(8)],
            "document_ids": [f"10000000-0000-0000-0000-{index:012d}" for index in range(5)],
        }
    )

    assert serializer.is_valid() is False
    assert "document_ids" in serializer.errors
