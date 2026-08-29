import assert from "node:assert/strict";
import test from "node:test";

import { __socialImageTestables as subject } from "../src/publishers/social-image.js";

test("prepares required fields with unicode-safe limits and normalized tags", () => {
  const result = subject.prepareFields("xiaohongshu", {
    title: `${"标题".repeat(12)}🙂`,
    contentText: " 正文内容 ",
    contentHtml: "",
    tags: ["#品牌", "品牌", "GEO\n优化", "", "搜索"],
  });

  assert.equal(result.ok, true);
  if (!result.ok) return;
  assert.equal(Array.from(result.title).length, 20);
  assert.deepEqual(result.tags, ["品牌", "GEO 优化", "搜索"]);
  assert.match(result.body, /#品牌 #GEO 优化 #搜索$/);
});

test("rejects blank title or blank content before opening a browser", () => {
  assert.deepEqual(
    subject.prepareFields("douyin", { title: " ", contentText: "正文", contentHtml: "", tags: [] }),
    { ok: false, safeErrorCode: "content_rejected" },
  );
  assert.deepEqual(
    subject.prepareFields("douyin", { title: "标题", contentText: " ", contentHtml: "<p> </p>", tags: [] }),
    { ok: false, safeErrorCode: "content_rejected" },
  );
});

test("failure classification gives required and media errors precedence", () => {
  assert.equal(subject.classifyFailureText("xiaohongshu", "发布成功，但请输入标题"), "content_rejected");
  assert.equal(subject.classifyFailureText("douyin", "图片上传失败，请重试"), "media_invalid");
  assert.equal(subject.classifyFailureText("douyin", "发布成功"), "");
});

test("management and public status URLs are allowlisted", () => {
  assert.equal(subject.safePlatformUrl("xiaohongshu", "https://creator.xiaohongshu.com/publish/manage", "management"), true);
  assert.equal(subject.safePlatformUrl("xiaohongshu", "https://www.xiaohongshu.com/explore/64cafe001122", "public"), true);
  assert.equal(subject.safePlatformUrl("douyin", "https://www.douyin.com/note/734567890123", "public"), true);
  assert.equal(subject.safePlatformUrl("douyin", "https://creator.douyin.com.evil.example/manage", "management"), false);
  assert.equal(subject.safePlatformUrl("xiaohongshu", "http://creator.xiaohongshu.com/manage", "management"), false);
  assert.equal(subject.safePlatformUrl("xiaohongshu", "https://user:pass@creator.xiaohongshu.com/manage", "management"), false);
});

test("returned URLs remove credential-like query values", () => {
  assert.equal(
    subject.sanitizedUrl("https://creator.douyin.com/manage?id=123&session_token=secret&code=one#fragment"),
    "https://creator.douyin.com/manage?id=123",
  );
  assert.equal(subject.extractExternalPostId("douyin", "https://www.douyin.com/note/734567890123"), "734567890123");
  assert.equal(subject.extractExternalPostId("xiaohongshu", "https://creator.xiaohongshu.com/publish/upload"), undefined);
});

test("result title binding requires the complete platform title", () => {
  const expected = "【验123456abcd】广州品牌优化";
  assert.equal(subject.titleMatches(`草稿 ${expected} 已保存`, expected), true);
  assert.equal(subject.titleMatches("【验123456", expected), false);
  assert.equal(subject.titleMatches("广州品牌优化", expected), false);
});

test("asset URLs and stored browser sessions fail closed", () => {
  assert.equal(subject.validateAssetUrl("https://assets.example/image.png"), true);
  assert.equal(subject.validateAssetUrl("file:///tmp/image.png"), false);
  assert.equal(subject.validateAssetUrl("https://user:pass@assets.example/image.png"), false);

  assert.equal(subject.hasStoredSession("xiaohongshu", { cookies: [] }), false);
  assert.equal(
    subject.hasStoredSession("xiaohongshu", {
      origins: [{ origin: "https://creator.xiaohongshu.com", localStorage: [{ name: "creator-token", value: "present" }] }],
    }),
    true,
  );
  assert.equal(
    subject.hasStoredSession("douyin", {
      origins: [{ origin: "https://evil.example", localStorage: [{ name: "token", value: "present" }] }],
    }),
    false,
  );
});
