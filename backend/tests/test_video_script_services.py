from types import SimpleNamespace

import pytest

from apps.articles.services import ContentError
from apps.articles.video_services import _fit_scene_durations, _normalize_video_output


def test_video_scene_durations_are_fitted_to_requested_length():
    assert sum(_fit_scene_durations([3, 7, 12], 30)) == 30


def test_video_output_normalizes_timing_and_keeps_three_hooks():
    job = SimpleNamespace(input_snapshot={"config": {"duration_seconds": 30}})
    output = _normalize_video_output(
        job,
        {
            "title": "为什么企业需要做 GEO",
            "hooks": ["钩子一", "钩子二", "钩子三", "备用钩子"],
            "scenes": [
                {
                    "visual": "人物正面出镜",
                    "voiceover": "先讲用户痛点。",
                    "subtitle": "AI 搜索找不到你？",
                    "duration_seconds": 4,
                },
                {
                    "visual": "产品页面录屏",
                    "voiceover": "再展示检测与优化流程。",
                    "subtitle": "先检测，再优化",
                    "duration_seconds": 11,
                },
                {
                    "visual": "品牌收尾",
                    "voiceover": "最后给出明确行动建议。",
                    "subtitle": "开始 GEO 检测",
                    "duration_seconds": 10,
                },
            ],
            "full_voiceover": "先讲用户痛点。再展示检测与优化流程。最后给出明确行动建议。",
            "cta": "现在开始检测。",
        },
    )
    assert output["duration_seconds"] == 30
    assert len(output["hooks"]) == 3
    assert output["scenes"][0]["start"] == 0
    assert output["scenes"][-1]["end"] == 30


def test_video_output_rejects_unexpected_schema():
    job = SimpleNamespace(input_snapshot={"config": {"duration_seconds": 30}})
    with pytest.raises(ContentError):
        _normalize_video_output(job, {"title": "bad"})
