export type LoginPlatform = Readonly<{
  key: string;
  name: string;
  loginUrl: string;
  successCookies: string[];
  cookieDomains: string[];
}>;

// 登录判定只使用明确的身份会话 Cookie，不使用普遍存在的匿名统计 Cookie。
// 这些平台仍需在显问真实测试账号中逐个平台验证，后端 enablelist 默认不会开放。
export const LOGIN_PLATFORMS: Readonly<Record<string, LoginPlatform>> = {
  zhihu: {
    key: "zhihu",
    name: "知乎",
    loginUrl: "https://www.zhihu.com/signin",
    successCookies: ["z_c0"],
    cookieDomains: [".zhihu.com", "api.zhihu.com", "zhuanlan.zhihu.com"],
  },
  toutiao: {
    key: "toutiao",
    name: "今日头条",
    loginUrl: "https://mp.toutiao.com/",
    successCookies: ["sid_tt", "sessionid"],
    cookieDomains: [".toutiao.com", "mp.toutiao.com"],
  },
  baijiahao: {
    key: "baijiahao",
    name: "百家号",
    loginUrl: "https://baijiahao.baidu.com/",
    successCookies: ["BDUSS"],
    cookieDomains: [".baidu.com", "baijiahao.baidu.com", "passport.baidu.com"],
  },
  xiaohongshu: {
    key: "xiaohongshu",
    name: "小红书",
    loginUrl: "https://creator.xiaohongshu.com/",
    successCookies: ["web_session", "galaxy_creator_session_id"],
    cookieDomains: [".xiaohongshu.com", ".edith.xiaohongshu.com"],
  },
  weibo: {
    key: "weibo",
    name: "微博",
    loginUrl: "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&disp=popup&url=https%3A%2F%2Fweibo.com%2Fu%2F0",
    successCookies: ["SUB"],
    cookieDomains: [".weibo.com", ".sina.com.cn"],
  },
  bilibili: {
    key: "bilibili",
    name: "B站专栏",
    loginUrl: "https://passport.bilibili.com/login",
    successCookies: ["SESSDATA"],
    cookieDomains: [".bilibili.com", "api.bilibili.com", "member.bilibili.com"],
  },
  douyin: {
    key: "douyin",
    name: "抖音图文",
    loginUrl: "https://creator.douyin.com/",
    successCookies: ["sessionid", "sid_tt"],
    cookieDomains: [".douyin.com", "creator.douyin.com"],
  },
  qq: {
    key: "qq",
    name: "企鹅号",
    loginUrl: "https://om.qq.com/userAuth/login",
    successCookies: ["p_skey"],
    cookieDomains: [".qq.com", ".om.qq.com"],
  },
  csdn: {
    key: "csdn",
    name: "CSDN",
    loginUrl: "https://passport.csdn.net/login",
    successCookies: ["UserToken", "UserSecret"],
    cookieDomains: [".csdn.net", "bizapi.csdn.net", "editor.csdn.net"],
  },
  juejin: {
    key: "juejin",
    name: "掘金",
    loginUrl: "https://juejin.cn/login",
    successCookies: ["sessionid"],
    cookieDomains: [".juejin.cn", "api.juejin.cn"],
  },
  cnblogs: {
    key: "cnblogs",
    name: "博客园",
    loginUrl: "https://account.cnblogs.com/signin",
    successCookies: [".CNBlogsCookie"],
    cookieDomains: [".cnblogs.com", "account.cnblogs.com", "i.cnblogs.com"],
  },
  oschina: {
    key: "oschina",
    name: "开源中国",
    loginUrl: "https://www.oschina.net/action/user/hash_login",
    successCookies: ["_user_token"],
    cookieDomains: [".oschina.net", "my.oschina.net"],
  },
  segmentfault: {
    key: "segmentfault",
    name: "思否",
    loginUrl: "https://segmentfault.com/user/login",
    successCookies: ["SFSSID", "PHPSESSID_sf"],
    cookieDomains: [".segmentfault.com", "segmentfault.com"],
  },
  jianshu: {
    key: "jianshu",
    name: "简书",
    loginUrl: "https://www.jianshu.com/sign_in",
    successCookies: ["remember_user_token"],
    cookieDomains: [".jianshu.com", "www.jianshu.com"],
  },
  douban: {
    key: "douban",
    name: "豆瓣",
    loginUrl: "https://accounts.douban.com/passport/login",
    successCookies: ["dbcl2"],
    cookieDomains: [".douban.com", "accounts.douban.com"],
  },
  sohu: {
    key: "sohu",
    name: "搜狐号",
    loginUrl: "https://mp.sohu.com/mp/login",
    // SUV/IPLOC 可能在匿名访问时存在，不能作为登录成功依据。
    successCookies: ["_mp_key"],
    cookieDomains: [".sohu.com", "mp.sohu.com"],
  },
};
