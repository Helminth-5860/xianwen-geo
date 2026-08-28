export type LoginPlatform = Readonly<{
  key: string;
  name: string;
  loginUrl: string;
  successCookie: string;
  cookieDomains: string[];
}>;

// 这些登录判定来自已审阅的开源适配器实现；仍需在显问真实测试账号中逐个平台验证后才开放。
export const LOGIN_PLATFORMS: Readonly<Record<string, LoginPlatform>> = {
  zhihu: {
    key: "zhihu",
    name: "知乎",
    loginUrl: "https://www.zhihu.com/",
    successCookie: "z_c0",
    cookieDomains: [".zhihu.com", "api.zhihu.com"],
  },
  juejin: {
    key: "juejin",
    name: "掘金",
    loginUrl: "https://juejin.cn/",
    successCookie: "uid_tt",
    cookieDomains: [".juejin.cn", "api.juejin.cn"],
  },
  csdn: {
    key: "csdn",
    name: "CSDN",
    loginUrl: "https://www.csdn.net/",
    successCookie: "UserName",
    cookieDomains: [".csdn.net", "bizapi.csdn.net"],
  },
  weibo: {
    key: "weibo",
    name: "微博",
    loginUrl: "https://weibo.com/",
    successCookie: "SUB",
    cookieDomains: [".weibo.com", ".sina.com.cn"],
  },
  xiaohongshu: {
    key: "xiaohongshu",
    name: "小红书",
    loginUrl: "https://creator.xiaohongshu.com/",
    successCookie: "galaxy_creator_session_id",
    cookieDomains: [".xiaohongshu.com", ".edith.xiaohongshu.com"],
  },
  toutiao: {
    key: "toutiao",
    name: "今日头条",
    loginUrl: "https://mp.toutiao.com/",
    successCookie: "sessionid",
    cookieDomains: [".toutiao.com"],
  },
  bilibili: {
    key: "bilibili",
    name: "B站专栏",
    loginUrl: "https://www.bilibili.com/",
    successCookie: "SESSDATA",
    cookieDomains: [".bilibili.com", "api.bilibili.com"],
  },
  qq: {
    key: "qq",
    name: "企鹅号",
    loginUrl: "https://om.qq.com/",
    successCookie: "userid",
    cookieDomains: [".qq.com", ".om.qq.com"],
  },
};
