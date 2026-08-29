from apps.publication_checks.models import PublicationVerificationCheck
from apps.publication_checks.network import PublicationProbeResult
from apps.publication_checks.services import _assess_probe


def _probe(*, status=200, body=b"", content_type="text/html; charset=utf-8"):
    return PublicationProbeResult(
        request_url="https://example.com/article",
        final_url="https://example.com/article",
        status=status,
        content_type=content_type,
        body=body,
        redirect_count=0,
        peer_ip="203.0.113.10",
    )


def _html(title: str, text: str) -> bytes:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body><article>{text}</article></body></html>"
    ).encode("utf-8")


def test_public_article_is_published():
    assessment = _assess_probe(
        _probe(
            body=_html(
                "企业如何做好 GEO",
                "这是一篇已经公开发布的文章正文，包含足够的有效文本用于确认页面内容。" * 4,
            )
        )
    )

    assert assessment.status == PublicationVerificationCheck.Status.PUBLISHED
    assert assessment.title == "企业如何做好 GEO"
    assert assessment.safe_failure_code == ""


def test_http_404_is_failed():
    assessment = _assess_probe(_probe(status=404, body=b"not found"))

    assert assessment.status == PublicationVerificationCheck.Status.FAILED
    assert assessment.safe_failure_code == "HTTP_404"


def test_http_403_is_unknown_instead_of_failed():
    assessment = _assess_probe(_probe(status=403, body=b"access denied"))

    assert assessment.status == PublicationVerificationCheck.Status.UNKNOWN
    assert assessment.safe_failure_code == "HTTP_403"


def test_rate_limit_is_unknown():
    assessment = _assess_probe(_probe(status=429, body=b"too many requests"))

    assert assessment.status == PublicationVerificationCheck.Status.UNKNOWN
    assert assessment.safe_failure_code == "HTTP_429"


def test_soft_not_found_page_is_failed():
    assessment = _assess_probe(
        _probe(body=_html("文章不存在", "抱歉，该内容已删除，请返回首页。"))
    )

    assert assessment.status == PublicationVerificationCheck.Status.FAILED
    assert assessment.safe_failure_code == "SOFT_NOT_FOUND"


def test_login_or_captcha_page_is_unknown():
    assessment = _assess_probe(
        _probe(body=_html("安全验证", "请先登录并完成人机验证后继续访问该文章。"))
    )

    assert assessment.status == PublicationVerificationCheck.Status.UNKNOWN
    assert assessment.safe_failure_code == "ACCESS_CHALLENGE"


def test_legitimate_article_containing_number_404_is_not_soft_not_found():
    assessment = _assess_probe(
        _probe(
            body=_html(
                "404 个 GEO 案例复盘",
                "本文整理了 404 个公开案例，数字只是文章内容的一部分，并不表示页面不存在。"
                "文章页面本身可以被正常访问并包含完整正文。" * 4,
            )
        )
    )

    assert assessment.status == PublicationVerificationCheck.Status.PUBLISHED
    assert assessment.safe_failure_code == ""
