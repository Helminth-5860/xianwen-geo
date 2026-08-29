import assert from "node:assert/strict";
import test, { after, before } from "node:test";

import { BILIBILI_PUBLISHER_CONFIG, BilibiliPublisher } from "../src/publishers/bilibili.js";
import {
  BROWSER_SAFE_ERROR_MESSAGES,
  browserSafeErrorMessage,
  classifyPageEvidence,
  exactStatusTitleMatch,
  isPublicArticleUrl,
  isSafeStatusUrl,
  urlContainsExternalPostId,
  validateBrowserPublisherConfig,
  type BrowserPublisherConfig,
} from "../src/publishers/browser-form.js";
import { BROWSER_PUBLISHER_CONFIGS } from "../src/publishers/browser-configs.js";
import { CNBLOGS_PUBLISHER_CONFIG, CnblogsPublisher } from "../src/publishers/cnblogs.js";
import { CSDN_PUBLISHER_CONFIG, CsdnPublisher } from "../src/publishers/csdn.js";
import { DOUBAN_PUBLISHER_CONFIG, DoubanPublisher } from "../src/publishers/douban.js";
import { JIANSHU_PUBLISHER_CONFIG, JianshuPublisher } from "../src/publishers/jianshu.js";
import { JUEJIN_PUBLISHER_CONFIG, JuejinPublisher } from "../src/publishers/juejin.js";
import { OSCHINA_PUBLISHER_CONFIG, OschinaPublisher } from "../src/publishers/oschina.js";
import { QQ_PUBLISHER_CONFIG, QqPublisher } from "../src/publishers/qq.js";
import { SEGMENTFAULT_PUBLISHER_CONFIG, SegmentfaultPublisher } from "../src/publishers/segmentfault.js";
import { SOHU_PUBLISHER_CONFIG, SohuPublisher } from "../src/publishers/sohu.js";
import type { PlatformPublisher, PublicationInput } from "../src/publishers/types.js";
import { WEIBO_PUBLISHER_CONFIG, WeiboPublisher } from "../src/publishers/weibo.js";

const configs: readonly BrowserPublisherConfig[] = [
  WEIBO_PUBLISHER_CONFIG,
  BILIBILI_PUBLISHER_CONFIG,
  QQ_PUBLISHER_CONFIG,
  SOHU_PUBLISHER_CONFIG,
  CSDN_PUBLISHER_CONFIG,
  JUEJIN_PUBLISHER_CONFIG,
  CNBLOGS_PUBLISHER_CONFIG,
  OSCHINA_PUBLISHER_CONFIG,
  SEGMENTFAULT_PUBLISHER_CONFIG,
  JIANSHU_PUBLISHER_CONFIG,
  DOUBAN_PUBLISHER_CONFIG,
];

const publishers: readonly PlatformPublisher[] = [
  new WeiboPublisher(),
  new BilibiliPublisher(),
  new QqPublisher(),
  new SohuPublisher(),
  new CsdnPublisher(),
  new JuejinPublisher(),
  new CnblogsPublisher(),
  new OschinaPublisher(),
  new SegmentfaultPublisher(),
  new JianshuPublisher(),
  new DoubanPublisher(),
];

const publicSamples: Readonly<Record<string, string>> = {
  weibo: "https://weibo.com/ttarticle/p/show?id=230940123456789",
  bilibili: "https://www.bilibili.com/read/cv123456",
  qq: "https://new.qq.com/rain/a/20260829A01ABC00",
  sohu: "https://www.sohu.com/a/123456_789012",
  csdn: "https://blog.csdn.net/example/article/details/123456",
  juejin: "https://juejin.cn/post/1234567890123456789",
  cnblogs: "https://www.cnblogs.com/example/p/123456.html",
  oschina: "https://my.oschina.net/example/blog/123456",
  segmentfault: "https://segmentfault.com/a/1190000041234567",
  jianshu: "https://www.jianshu.com/p/a1b2c3d4e5f6",
  douban: "https://www.douban.com/note/123456789/",
};

const previousExperimentalKeys = process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS;

before(() => {
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = "";
});

after(() => {
  if (previousExperimentalKeys === undefined) delete process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS;
  else process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = previousExperimentalKeys;
});

function credentialsFor(config: BrowserPublisherConfig) {
  return {
    cookies: [
      {
        name: config.authCookieNames[0],
        value: "test-session-value",
        domain: new URL(config.editorUrl).hostname,
        path: "/",
      },
    ],
  };
}

function publicationInput(config: BrowserPublisherConfig, withCredentials: boolean): PublicationInput {
  return {
    targetId: `target-${config.platformKey}`,
    title: "验收测试标题",
    contentHtml: "<p>验收测试正文</p>",
    contentText: "验收测试正文",
    tags: ["测试"],
    assets: [],
    credentials: withCredentials ? credentialsFor(config) : {},
    publishMode: "public",
  };
}

test("all specialized platform configs are complete and registered in the temporary config catalog", () => {
  assert.deepEqual(Object.keys(BROWSER_PUBLISHER_CONFIGS).sort(), configs.map((item) => item.platformKey).sort());
  for (const config of configs) {
    assert.deepEqual(validateBrowserPublisherConfig(config), [], config.platformKey);
    assert.ok(config.draft.actionSelectors?.length || config.draft.autoSaveWaitMs, config.platformKey);
    assert.ok(
      config.draft.successTexts.length || config.draft.successSelectors?.length || config.draft.urlPatterns?.length,
      config.platformKey,
    );
    assert.ok(config.publishSteps.every((step) => step.name && step.selectors.length), config.platformKey);
    assert.ok(config.statusItemSelectors?.length, config.platformKey);
    assert.ok(config.statusTitleSelectors?.length, config.platformKey);
  }
});

test("status binding uses an exact normalized title or exact URL identifier", () => {
  assert.equal(exactStatusTitleMatch("  本次\n文章标题 ", "本次 文章标题"), true);
  assert.equal(exactStatusTitleMatch("本次文章标题（旧）", "本次文章标题"), false);
  assert.equal(urlContainsExternalPostId("https://example.com/article/123?from=456", "123"), true);
  assert.equal(urlContainsExternalPostId("https://example.com/article/1234?from=456", "123"), false);
  assert.equal(urlContainsExternalPostId("https://example.com/article?id=abc-123", "abc-123"), true);
});

test("CSDN redirected editor route remains inside the explicit status allowlist", () => {
  assert.equal(isSafeStatusUrl("https://editor.csdn.net/md/123456", CSDN_PUBLISHER_CONFIG), true);
  assert.equal(isSafeStatusUrl("https://editor.csdn.net.evil.example/md/123456", CSDN_PUBLISHER_CONFIG), false);
});

test("dedicated classes expose only auth as verified until real-account acceptance", () => {
  assert.deepEqual(publishers.map((item) => item.platformKey), configs.map((item) => item.platformKey));
  for (const publisher of publishers) assert.deepEqual(publisher.verifiedCapabilities, ["auth"]);
});

test("status URLs are limited to explicit HTTPS platform routes", () => {
  for (const config of configs) {
    assert.equal(isSafeStatusUrl(config.editorUrl, config), true, config.platformKey);
    assert.equal(isSafeStatusUrl("https://evil.example/status", config), false, config.platformKey);
    const suffix = config.allowedHostSuffixes[0];
    assert.equal(isSafeStatusUrl(`https://${suffix}.evil.example/status`, config), false, config.platformKey);
    assert.equal(isSafeStatusUrl(config.editorUrl.replace("https://", "http://"), config), false, config.platformKey);
  }
});

test("only known public article URL shapes count as published evidence", () => {
  for (const config of configs) {
    const sample = publicSamples[config.platformKey];
    assert.ok(sample, config.platformKey);
    assert.equal(isPublicArticleUrl(sample, config), true, config.platformKey);
    assert.equal(isPublicArticleUrl(config.editorUrl, config), false, config.platformKey);
    const parsed = new URL(sample);
    const lookalike = `https://${parsed.hostname}.evil.example${parsed.pathname}${parsed.search}`;
    assert.equal(isPublicArticleUrl(lookalike, config), false, config.platformKey);
  }
});

test("publication evidence never turns an unconfirmed page into success", () => {
  for (const config of configs) {
    assert.deepEqual(classifyPageEvidence("编辑完成，可以发布", undefined, config), { kind: "unknown" }, config.platformKey);
    assert.deepEqual(classifyPageEvidence(config.successTexts[0], undefined, config), { kind: "submitted" }, config.platformKey);
    assert.deepEqual(
      classifyPageEvidence(config.successTexts[0], undefined, config, `帮助说明：${config.successTexts[0]}后可查看文章`),
      { kind: "unknown" },
      config.platformKey,
    );
    if (config.reviewTexts?.length) {
      assert.deepEqual(classifyPageEvidence(config.reviewTexts[0], undefined, config), { kind: "submitted" }, config.platformKey);
    }
    assert.deepEqual(
      classifyPageEvidence("发布失败，但页面仍显示发布成功", publicSamples[config.platformKey], config),
      { kind: "failed", safeErrorCode: "content_rejected" },
      config.platformKey,
    );
    assert.deepEqual(
      classifyPageEvidence("", publicSamples[config.platformKey], config),
      { kind: "published", publicUrl: publicSamples[config.platformKey] },
      config.platformKey,
    );
    assert.deepEqual(classifyPageEvidence("", "https://evil.example/article/1", config), { kind: "unknown" }, config.platformKey);
  }
});

test("validation prompts become action_required evidence instead of success", () => {
  for (const config of configs) {
    const prompt = config.validationTexts?.[0];
    assert.ok(prompt, config.platformKey);
    assert.deepEqual(
      classifyPageEvidence(prompt, undefined, config),
      { kind: "action_required", safeErrorCode: "platform_fields_required" },
      config.platformKey,
    );
  }
});

test("safe browser error codes have Chinese user-facing wording", () => {
  for (const code of Object.keys(BROWSER_SAFE_ERROR_MESSAGES) as Array<keyof typeof BROWSER_SAFE_ERROR_MESSAGES>) {
    const message = browserSafeErrorMessage(code);
    assert.match(message, /[\u3400-\u9fff]/, code);
    assert.ok(message.length >= 8, code);
  }
});

test("auth checks reject missing platform identity cookies before browser validation", async () => {
  for (let index = 0; index < publishers.length; index += 1) {
    const publisher = publishers[index];
    const config = configs[index];
    assert.equal(
      (await publisher.checkAuth({ cookies: [{ name: "anonymous_cookie", value: "1", domain: new URL(config.editorUrl).hostname, path: "/" }] })).ok,
      false,
      config.platformKey,
    );
  }
});

test("closed platform gate fails before opening a browser and never reports success", async () => {
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = "";
  for (let index = 0; index < publishers.length; index += 1) {
    const result = await publishers[index].publish(publicationInput(configs[index], true));
    assert.deepEqual(
      result,
      {
        success: false,
        platformKey: configs[index].platformKey,
        status: "action_required",
        safeErrorCode: "platform_not_verified",
      },
    );
  }
});

test("enabled platform without identity credentials returns auth_required before browser use", async () => {
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = configs.map((item) => item.platformKey).join(",");
  for (let index = 0; index < publishers.length; index += 1) {
    const result = await publishers[index].publish(publicationInput(configs[index], false));
    assert.equal(result.success, false, configs[index].platformKey);
    assert.equal(result.status, "auth_required", configs[index].platformKey);
    assert.equal(result.safeErrorCode, "authorization_required", configs[index].platformKey);
  }
});

test("unsafe status URL is rejected before browser use", async () => {
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = configs.map((item) => item.platformKey).join(",");
  for (let index = 0; index < publishers.length; index += 1) {
    const result = await publishers[index].checkStatus?.({
      credentials: credentialsFor(configs[index]),
      managementUrl: "https://evil.example/status",
    });
    assert.deepEqual(
      result,
      {
        platformKey: configs[index].platformKey,
        status: "unknown",
        safeErrorCode: "unsafe_status_url",
      },
    );
  }
});

test("safe status URL without an exact article binding is rejected before browser use", async () => {
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = configs.map((item) => item.platformKey).join(",");
  for (let index = 0; index < publishers.length; index += 1) {
    const result = await publishers[index].checkStatus?.({
      credentials: credentialsFor(configs[index]),
      managementUrl: configs[index].editorUrl,
    });
    assert.deepEqual(
      result,
      {
        platformKey: configs[index].platformKey,
        status: "unknown",
        safeErrorCode: "status_target_unbound",
      },
    );
  }
});
