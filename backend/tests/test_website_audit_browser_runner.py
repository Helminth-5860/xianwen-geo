from apps.website_audits.browser_runner import _float_metric, _int_metric, normalize_profiles


def test_browser_profiles_are_deduplicated_and_validated():
    assert normalize_profiles(["desktop", "mobile", "desktop", "invalid"]) == (
        "desktop",
        "mobile",
    )
    assert normalize_profiles([]) == ("mobile", "desktop")


def test_browser_metric_normalization_rejects_non_finite_values():
    assert _int_metric(123.6) == 124
    assert _int_metric(-5) == 0
    assert _int_metric(float("inf")) is None
    assert _float_metric(0.123456) == 0.12346
    assert _float_metric(float("nan")) is None
