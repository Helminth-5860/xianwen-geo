import assert from "node:assert/strict";
import test from "node:test";

import {
  baijiaPublicArticleId,
  isBoundBaijiaPublicUrl,
  isSafeBaijiaManagementUrl,
} from "../src/publishers/baijiahao.js";
import {
  isBoundToutiaoPublicUrl,
  isSafeToutiaoManagementUrl,
  toutiaoPublicArticleId,
} from "../src/publishers/toutiao.js";
import {
  classifyWechatPublishStatus,
  isSafeWechatArticleUrl,
  WechatPublisher,
} from "../src/publishers/wechat.js";
import {
  hasZhihuArticleEvidence,
  isZhihuAuthOrRiskUrl,
  isZhihuPublicUrlForArticle,
} from "../src/publishers/zhihu.js";

test("微信发布状态 4 明确归类为失败", () => {
  assert.equal(classifyWechatPublishStatus(0), "published");
  assert.equal(classifyWechatPublishStatus(1), "pending");
  assert.equal(classifyWechatPublishStatus(4), "failed");
  assert.equal(classifyWechatPublishStatus(999), "unknown");
});
test("微信只接受公众号文章白名单地址", () => {
  assert.equal(isSafeWechatArticleUrl("https://mp.weixin.qq.com/s?__biz=test"), true);
  assert.equal(isSafeWechatArticleUrl("https://mp.weixin.qq.com/s/example"), true);
  assert.equal(isSafeWechatArticleUrl("https://mp.weixin.qq.com.evil.example/s"), false);
  assert.equal(isSafeWechatArticleUrl("http://mp.weixin.qq.com/s"), false);
});

test("微信授权检查要求草稿接口明确可用", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (input) => {
      const url = String(input);
      assert.match(url, /\/cgi-bin\/draft\/count/);
      return new Response(JSON.stringify({ total_count: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };
    assert.equal((await new WechatPublisher().checkAuth({ access_token: "test-token" })).ok, true);

    globalThis.fetch = async () => new Response(JSON.stringify({}), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    assert.equal((await new WechatPublisher().checkAuth({ access_token: "test-token" })).ok, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("微信状态查询不会把失败状态 4 或仿冒链接报成成功", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ publish_status: 4 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    assert.deepEqual(
      await new WechatPublisher().checkStatus({ credentials: { access_token: "test-token" }, externalPostId: "publish-1" }),
      { platformKey: "wechat", status: "failed", safeErrorCode: "content_rejected" },
    );

    globalThis.fetch = async () => new Response(JSON.stringify({
      publish_status: 0,
      article_detail: { item: [{ article_url: "https://mp.weixin.qq.com.evil.example/s?id=1" }] },
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    assert.deepEqual(
      await new WechatPublisher().checkStatus({ credentials: { access_token: "test-token" }, externalPostId: "publish-1" }),
      { platformKey: "wechat", status: "submitted" },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("知乎结果必须是同一草稿 ID 的正式文章页并包含标题", () => {
  assert.equal(isZhihuPublicUrlForArticle("https://zhuanlan.zhihu.com/p/123456", "123456"), true);
  assert.equal(isZhihuPublicUrlForArticle("https://zhuanlan.zhihu.com/p/123456/edit", "123456"), false);
  assert.equal(isZhihuPublicUrlForArticle("https://zhuanlan.zhihu.com/p/999999", "123456"), false);
  assert.equal(isZhihuPublicUrlForArticle("https://zhuanlan.zhihu.com.evil.example/p/123456", "123456"), false);
  assert.equal(hasZhihuArticleEvidence("<h1>本次验收标题</h1><p>正文</p>", "123456", "本次验收标题"), true);
  assert.equal(hasZhihuArticleEvidence("<h1>另一篇文章</h1>", "123456", "本次验收标题"), false);
  assert.equal(hasZhihuArticleEvidence("安全验证 <h1>本次验收标题</h1>", "123456", "本次验收标题"), false);
  assert.equal(hasZhihuArticleEvidence("<h1>本次验收标题</h1>", "123456", undefined), false);
});

test("知乎登录、编辑和风控页不能作为发布结果", () => {
  assert.equal(isZhihuAuthOrRiskUrl("https://www.zhihu.com/signin"), true);
  assert.equal(isZhihuAuthOrRiskUrl("https://www.zhihu.com/account/unhuman?type=unhuman"), true);
  assert.equal(isZhihuAuthOrRiskUrl("https://zhuanlan.zhihu.com/p/123456"), false);
});

test("头条管理页和公开文章地址使用严格白名单并绑定文章", () => {
  assert.equal(isSafeToutiaoManagementUrl("https://mp.toutiao.com/profile_v4/graphic/edit?id=123456"), true);
  assert.equal(isSafeToutiaoManagementUrl("https://mp.toutiao.com.evil.example/profile_v4/graphic/edit?id=123456"), false);
  assert.equal(toutiaoPublicArticleId("https://www.toutiao.com/article/123456789/"), "123456789");
  assert.equal(toutiaoPublicArticleId("https://evil.example/article/123456789/"), "");
  assert.equal(
    isBoundToutiaoPublicUrl("https://www.toutiao.com/article/123456789/", "123456789", "本次标题", "本次标题"),
    true,
  );
  assert.equal(
    isBoundToutiaoPublicUrl("https://www.toutiao.com/article/999999999/", "123456789", "本次标题", "本次标题"),
    false,
  );
  assert.equal(
    isBoundToutiaoPublicUrl("https://www.toutiao.com/article/123456789/", "123456789", "本次标题", "其他文章"),
    false,
  );
});

test("百家号管理页和公开文章地址使用严格白名单并绑定文章", () => {
  assert.equal(isSafeBaijiaManagementUrl("https://baijiahao.baidu.com/builder/rc/edit?id=123456"), true);
  assert.equal(isSafeBaijiaManagementUrl("https://baijiahao.baidu.com.evil.example/builder/rc/edit?id=123456"), false);
  assert.equal(baijiaPublicArticleId("https://baijiahao.baidu.com/s?id=123456789"), "123456789");
  assert.equal(baijiaPublicArticleId("https://evil.example/s?id=123456789"), "");
  assert.equal(
    isBoundBaijiaPublicUrl("https://baijiahao.baidu.com/s?id=123456789", "123456789", "本次标题", "本次标题"),
    true,
  );
  assert.equal(
    isBoundBaijiaPublicUrl("https://baijiahao.baidu.com/s?id=999999999", "123456789", "本次标题", "本次标题"),
    false,
  );
  assert.equal(
    isBoundBaijiaPublicUrl("https://mbd.baidu.com/newspage/data/landingshare?context=test", undefined, "本次标题", "其他文章"),
    false,
  );
});
