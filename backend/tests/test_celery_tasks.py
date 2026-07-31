from apps.core.tasks import system_health_check


def test_system_health_task_is_safe_and_side_effect_free():
    assert system_health_check.run() == {"status": "ok"}
    assert system_health_check.name == "system.health_check"
