from apps.website_audits.tasks import execute_website_audit_task


def test_static_website_audit_task_has_customer_facing_time_limits():
    assert execute_website_audit_task.soft_time_limit == 90
    assert execute_website_audit_task.time_limit == 105
