from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.articles.models import Article
from apps.publications.models import (
    AutoPublishPolicy,
    PlatformAccount,
    PublicationJob,
    PublicationPlatform,
    PublicationTarget,
)
from apps.publications.services import (
    PublicationInputError,
    get_or_create_policy,
    platform_catalog,
    update_policy,
)
from apps.publications.tasks import dispatch_due_publication_targets_task
from apps.subjects.models import Subject, SubjectType, SubjectVersion
from apps.users.models import User


class PublicationTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            phone="13800009101",
            password="Xianwen-Test-Password-2026!",
            nickname="自动发文测试",
            is_test_account=True,
        )
        self.subject_type = SubjectType.objects.create(
            key="publication-test-company",
            name="自动发文测试主体",
            schema_version=1,
            version=1,
        )
        self.subject_a, self.version_a = self._subject("主体A")
        self.subject_b, self.version_b = self._subject("主体B")

    def _subject(self, name: str):
        subject = Subject.objects.create(
            user=self.user,
            subject_type=self.subject_type,
            status=Subject.Status.ACTIVE,
            draft_values={},
            schema_version=1,
            schema_snapshot_format_version=1,
            schema_snapshot={},
            schema_digest="a" * 64,
            version=1,
        )
        version = SubjectVersion.objects.create(
            subject=subject,
            version_no=1,
            field_values={},
            schema_version=1,
            schema_snapshot_format_version=1,
            schema_snapshot={},
            schema_digest="a" * 64,
            field_values_digest="b" * 64,
            semantic_digest="c" * 64,
            official_name=name,
            created_by=self.user,
        )
        subject.current_version = version
        subject.save(update_fields=("current_version", "updated_at"))
        return subject, version

    def _article(self, subject, version, title="GEO 自动发文测试"):
        return Article.objects.create(
            user=self.user,
            subject=subject,
            subject_version=version,
            custom_type="行业知识",
            title=title,
            content="这是一篇用于自动发文测试的完整文章内容。",
            status=Article.Status.READY,
            moderation_status=Article.Moderation.PASSED,
        )

    def test_domestic_platform_catalog_is_exactly_seventeen_and_held_for_validation(self):
        platforms = PublicationPlatform.objects.select_related("channel").order_by("channel__key")
        self.assertEqual(platforms.count(), 17)
        keys = set(platforms.values_list("channel__key", flat=True))
        self.assertEqual(
            keys,
            {
                "wechat",
                "toutiao",
                "baijiahao",
                "zhihu",
                "xiaohongshu",
                "weibo",
                "bilibili",
                "douyin",
                "qq",
                "sohu",
                "csdn",
                "juejin",
                "cnblogs",
                "oschina",
                "segmentfault",
                "jianshu",
                "douban",
            },
        )
        self.assertFalse({"medium", "hashnode", "devto"} & keys)
        self.assertEqual(platforms.exclude(channel__key="sohu").filter(validation_status="testing").count(), 16)
        self.assertEqual(platforms.get(channel__key="sohu").validation_status, "paused")

    def test_default_policy_uses_customer_assets_first_standard_visuals(self):
        policy = get_or_create_policy(user=self.user, subject_id=self.subject_a.pk)
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.distribution_strategy, AutoPublishPolicy.DistributionStrategy.SMART)
        self.assertEqual(policy.image_strategy, AutoPublishPolicy.ImageStrategy.PREFER_CUSTOMER)
        self.assertEqual(policy.image_richness, AutoPublishPolicy.ImageRichness.STANDARD)

    def test_platform_catalog_never_serializes_encrypted_authorization_state(self):
        platform = PublicationPlatform.objects.select_related("channel").get(channel__key="wechat")
        PlatformAccount.objects.create(
            user=self.user,
            subject=self.subject_a,
            platform=platform,
            auth_method=platform.auth_mode,
            auth_status=PlatformAccount.AuthStatus.AUTHORIZED,
            encrypted_auth_state="THIS-MUST-NEVER-LEAVE-THE-BACKEND",
            display_name="测试公众号",
        )
        payload = platform_catalog(user=self.user, subject_id=self.subject_a.pk)
        self.assertNotIn("THIS-MUST-NEVER-LEAVE-THE-BACKEND", repr(payload))
        account = next(item["account"] for item in payload if item["key"] == "wechat")
        self.assertNotIn("encrypted_auth_state", account)
        self.assertNotIn("auth_metadata", account)

    def test_policy_optimistic_version_rejects_stale_update(self):
        policy = get_or_create_policy(user=self.user, subject_id=self.subject_a.pk)
        updated = update_policy(
            user=self.user,
            subject_id=self.subject_a.pk,
            data={"enabled": True},
            expected_version=policy.version,
        )
        self.assertTrue(updated.enabled)
        with self.assertRaises(PublicationInputError) as caught:
            update_policy(
                user=self.user,
                subject_id=self.subject_a.pk,
                data={"enabled": False},
                expected_version=policy.version,
            )
        self.assertEqual(caught.exception.code, "PUBLICATION_POLICY_VERSION_CONFLICT")

    def test_cross_subject_manual_publish_rejected_without_writing_job(self):
        article = self._article(self.subject_b, self.version_b)
        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.post(
            f"/api/v1/subjects/{self.subject_a.pk}/auto-publish/jobs",
            {"article_id": str(article.pk)},
            format="json",
            HTTP_IDEMPOTENCY_KEY="cross-subject-test",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PublicationJob.objects.count(), 0)

    def test_dispatcher_claims_target_once_before_enqueuing(self):
        article = self._article(self.subject_a, self.version_a)
        policy = get_or_create_policy(user=self.user, subject_id=self.subject_a.pk)
        platform = PublicationPlatform.objects.select_related("channel").get(channel__key="wechat")
        account = PlatformAccount.objects.create(
            user=self.user,
            subject=self.subject_a,
            platform=platform,
            auth_method=platform.auth_mode,
            auth_status=PlatformAccount.AuthStatus.AUTHORIZED,
            encrypted_auth_state="encrypted-test-state",
        )
        job = PublicationJob.objects.create(
            user=self.user,
            subject=self.subject_a,
            article=article,
            policy=policy,
            status=PublicationJob.Status.SCHEDULED,
            policy_snapshot={},
            distribution_plan={},
            visual_plan={},
            idempotency_key_digest="d" * 64,
        )
        target = PublicationTarget.objects.create(
            job=job,
            platform=platform,
            account=account,
            status=PublicationTarget.Status.SCHEDULED,
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )
        with patch("apps.publications.tasks.execute_publication_target_task.apply_async") as enqueue:
            first = dispatch_due_publication_targets_task()
            second = dispatch_due_publication_targets_task()
        target.refresh_from_db()
        self.assertEqual(first["dispatched"], 1)
        self.assertEqual(second["dispatched"], 0)
        self.assertEqual(target.status, PublicationTarget.Status.PUBLISHING)
        enqueue.assert_called_once()
