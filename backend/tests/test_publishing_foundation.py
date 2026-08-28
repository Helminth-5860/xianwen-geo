from django.test import SimpleTestCase, override_settings

from apps.publishing.catalog import PLATFORM_BY_KEY, PLATFORMS, platform_payload
from apps.publishing.security import decrypt_secret, digest_one_time_token, encrypt_secret, issue_one_time_token


class PublishingCatalogTests(SimpleTestCase):
    def test_domestic_platform_catalog_contains_17_unique_platforms(self):
        self.assertEqual(len(PLATFORMS), 17)
        self.assertEqual(len(PLATFORM_BY_KEY), 17)
        self.assertEqual(len({item.name for item in PLATFORMS}), 17)
        self.assertNotIn("medium", PLATFORM_BY_KEY)
        self.assertNotIn("devto", PLATFORM_BY_KEY)
        self.assertNotIn("hashnode", PLATFORM_BY_KEY)

    def test_only_explicitly_enabled_and_runtime_ready_platforms_are_open(self):
        payload = platform_payload({"wechat", "zhihu"})
        by_key = {item["key"]: item for item in payload}
        # 微信还要求第三方平台 component_verify_ticket 有效；测试环境没有票据，所以保持关闭。
        self.assertFalse(by_key["wechat"]["authorization_enabled"])
        self.assertTrue(by_key["zhihu"]["authorization_enabled"])
        self.assertFalse(by_key["xiaohongshu"]["authorization_enabled"])
        self.assertEqual(by_key["xiaohongshu"]["verification_state"], "validation")


class PublishingCredentialSecurityTests(SimpleTestCase):
    @override_settings(SECRET_KEY="test-secret-key-for-publishing-encryption", PUBLISHING_CREDENTIAL_ENCRYPTION_KEY="")
    def test_credentials_are_encrypted_and_can_be_restored(self):
        source = {"cookies": [{"name": "session", "value": "secret-cookie"}], "token": "private-token"}
        ciphertext = encrypt_secret(source)
        self.assertNotIn("secret-cookie", ciphertext)
        self.assertNotIn("private-token", ciphertext)
        self.assertEqual(decrypt_secret(ciphertext), source)

    def test_one_time_authorization_token_is_not_stored_in_plaintext(self):
        token, digest = issue_one_time_token()
        self.assertNotEqual(token, digest)
        self.assertEqual(digest_one_time_token(token), digest)
        self.assertEqual(len(digest), 64)
