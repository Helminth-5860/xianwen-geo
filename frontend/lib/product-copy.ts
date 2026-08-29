export const XIANWEN_PRODUCT_TERMS = Object.freeze({
  overview: "GEO 总览",
  subjectArchive: "主体档案",
  keywords: "关键词中心",
  questions: "问题库",
  detection: "AI 可见度检测",
  insights: "GEO 洞察",
  optimization: "优化方案",
  websiteEntity: "官网实体建设",
  mapEntity: "地图实体建设",
  mediaSignals: "媒体信号建设",
  contentAssets: "内容资产",
});

export const PLAN_APPLICATION_STATUS_LABELS = Object.freeze({
  pending: "待处理",
  contacted: "已联系",
  closed: "已关闭",
  cancelled: "已取消",
  activated: "已开通",
});

export const SUBSCRIPTION_STATUS_LABELS = Object.freeze({
  active: "使用中",
  expired: "已到期",
  terminated: "已结束",
});

export const SUBSCRIPTION_CHANGE_STATUS_LABELS = Object.freeze({
  scheduled: "等待生效",
  executed: "已生效",
  cancelled: "已取消",
  failed: "未能完成",
});

export const SUBSCRIPTION_CHANGE_TYPE_LABELS = Object.freeze({
  renewal: "续费",
  upgrade: "升级套餐",
  downgrade: "调整套餐",
  replacement: "更换套餐",
  trial_conversion: "转为正式套餐",
});

export const REPORT_SHARE_STATUS_LABELS = Object.freeze({
  active: "可访问",
  closed: "已关闭",
  expired: "已过期",
});

const AI_MODEL_DISPLAY_NAMES: Readonly<Record<string, string>> = Object.freeze({
  deepseek: "DeepSeek",
  doubao: "豆包",
  qwen: "千问",
  tongyi_qianwen: "千问",
  hunyuan: "混元",
  wenxin: "文心一言",
  ernie: "文心一言",
  kimi: "Kimi",
  glm: "智谱 GLM",
  spark: "讯飞星火",
});

export function aiModelDisplayName(modelKey: string): string {
  return AI_MODEL_DISPLAY_NAMES[modelKey.trim().toLowerCase()] ?? "AI 平台";
}

export function publicPlanBenefitLines(benefits: Readonly<Record<string, unknown>>) {
  const numberValue = (key: string) => {
    const value = benefits[key];
    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
  };
  const lines: string[] = [];
  const subjects = numberValue("subject_active_limit");
  const models = numberValue("max_models_per_detection");
  const questions = numberValue("max_questions_per_detection");
  const detections = numberValue("detection_points");
  const articles = numberValue("article_credits");
  const images = numberValue("image_credits");
  const videos = numberValue("video_credits");
  const storage = numberValue("storage_bytes");

  if (subjects !== undefined) lines.push(`最多管理 ${subjects} 个主体`);
  if (models !== undefined) lines.push(`单次检测最多覆盖 ${models} 个 AI 平台`);
  if (questions !== undefined) lines.push(`单次检测最多选择 ${questions} 个问题`);
  if (detections !== undefined) lines.push(`${detections} 个检测点数`);
  if (articles !== undefined) lines.push(`${articles} 次文章生成`);
  if (images !== undefined) lines.push(`${images} 次图片生成`);
  if (videos !== undefined) lines.push(`${videos} 秒视频生成`);
  if (storage !== undefined) {
    const gigabytes = storage / 1024 ** 3;
    lines.push(
      `${gigabytes >= 1 ? `${Number(gigabytes.toFixed(1))} GB` : `${Math.round(storage / 1024 ** 2)} MB`} 资料空间`,
    );
  }
  if (benefits.white_label_enabled === true) lines.push("支持自定义品牌展示");
  if (benefits.report_export_enabled === true) lines.push("支持导出报告");
  if (benefits.report_share_enabled === true) lines.push("支持分享报告");
  return lines;
}

type UserFacingProblem = Readonly<{
  code?: string;
  status?: number;
}>;

const exactErrorMessages: Readonly<Record<string, string>> = Object.freeze({
  ACCOUNT_ALREADY_EXISTS: "该手机号已注册，请直接登录或找回密码。",
  ACCOUNT_UNAVAILABLE: "当前账号暂时无法使用，请联系管理员。",
  ADMIN_LOGIN_REQUIRED: "管理员账号请从管理员登录入口登录。",
  AUTH_CREDENTIALS_INVALID: "手机号、密码或验证码不正确，请重新输入。",
  AUTH_REQUIRED: "登录状态已失效，请重新登录后继续。",
  PERMISSION_DENIED: "你没有权限查看或操作这项内容。",
  RATE_LIMITED: "当前访问人数较多，请稍后再试。",
  RESOURCE_NOT_FOUND: "没有找到相关内容，它可能已被删除或失效。",
  VALIDATION_ERROR: "提交的信息有误，请检查后重新提交。",
  PLAN_REQUIRED: "当前套餐暂不包含这项功能，请先查看可用套餐。",
  QUOTA_INSUFFICIENT: "当前可用次数不足，请查看套餐与额度。",
  REPORT_EXPORT_FAILED: "报告导出未完成，请重新尝试。",
  REPORT_SHARE_CLOSED: "该报告分享已关闭。",
  REPORT_SHARE_EXPIRED: "该报告分享已过期。",
  REPORT_SHARE_EXPIRY_INVALID: "分享有效期设置有误，请重新选择。",
  REPORT_SHARE_NOT_ENTITLED: "当前套餐暂不支持报告分享。",
  REPORT_SHARE_PASSWORD_INVALID: "访问密码不正确，请重新输入。",
  REPORT_SHARE_PASSWORD_REQUIRED: "请输入访问密码后继续。",
  REPORT_SHARE_PDF_UNAVAILABLE: "报告文件暂时无法下载，请稍后再试。",
  REPORT_SHARE_UNAVAILABLE: "该报告分享暂时无法访问。",
  REPORT_SHARE_UNLOCK_RATE_LIMITED: "尝试次数较多，请稍后再输入密码。",
  SUBJECT_LIMIT_REACHED: "主体数量已达到当前套餐上限。",
  SUBJECT_REQUIRED_FIELDS_INCOMPLETE: "企业资料尚未填写完整，请补充必填信息。",
  SUBJECT_REVIEW_PENDING: "企业资料正在确认中，请稍候。",
  SUBJECT_REVIEW_REJECTED: "企业资料未通过确认，请根据提示修改后重新保存。",
  COMPETITOR_LIMIT_REACHED: "当前主体最多设置 3 家核心竞品。",
  COMPETITOR_DUPLICATE: "这家竞品已设置，请勿重复添加。",
  COMPETITOR_IS_SUBJECT: "不能将当前主体设置为自己的竞品。",
  COMPETITOR_NOT_FOUND: "这家竞品已被移除，请刷新页面后重试。",
});

const forbiddenTechnicalMessage =
  /(?:\b(?:provider|runtime|adapter|payload|request|response|endpoint|worker|queue|job|task\s*id|request\s*id|correlation\s*id|token\s*usage|retry|timeout|fallback|degraded|mock|staging|production|environment|api\s*(?:key|credential)?|http|json|schema|config|debug|log|exception|traceback|cache|database|redis|celery|docker|ssr|csr|hydration|component|props|hook|client\s*boundary|server\s*component)\b|[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+|Traceback|\bat\s+\S+\([^)]*:\d+:\d+\))/i;

const internalChineseMessage =
  /(?:接口|后端|运维|开发环境|生产环境|测试环境|调试|日志|异常堆栈|请求|任务|队列|凭证|鉴权|供应商|令牌|载荷|运行时|适配器|执行器|降级处理|兼容旧|暂未接入|待开发|先占位|技术债|第一阶段|第二阶段)/;

function hasCodePart(code: string, part: string) {
  return code === part || code.includes(`_${part}`) || code.startsWith(`${part}_`);
}

export function userFacingApiError(problem: UserFacingProblem): string {
  const code = (problem.code ?? "").trim().toUpperCase();
  const exact = exactErrorMessages[code];
  if (exact) return exact;

  if (problem.status === 401 || hasCodePart(code, "AUTH_REQUIRED")) {
    return "登录状态已失效，请重新登录后继续。";
  }
  if (problem.status === 403 || code.includes("PERMISSION") || code.includes("FORBIDDEN")) {
    return "你没有权限查看或操作这项内容。";
  }
  if (problem.status === 404 || code.includes("NOT_FOUND")) {
    return "没有找到相关内容，它可能已被删除或失效。";
  }
  if (problem.status === 429 || code.includes("RATE_LIMIT")) {
    return "当前访问人数较多，请稍后再试。";
  }
  if (code.includes("QUOTA") || code.includes("LIMIT_EXCEEDED")) {
    return "当前可用次数不足，请查看套餐与额度。";
  }
  if (code.includes("PLAN_REQUIRED") || code.includes("NOT_ENTITLED")) {
    return "当前套餐暂不包含这项功能，请先查看可用套餐。";
  }
  if (
    code.includes("IN_PROGRESS") ||
    code.includes("STATE_CONFLICT") ||
    code.includes("VERSION_CONFLICT") ||
    code.includes("IDEMPOTENCY_CONFLICT")
  ) {
    return "内容刚刚发生变化，请刷新后再操作。";
  }
  if (
    code.includes("VALUES_INVALID") ||
    code.includes("INPUT_INVALID") ||
    code.includes("VALIDATION") ||
    code.includes("SCHEMA")
  ) {
    return "提交的信息有误，请检查后重新提交。";
  }
  if (code.includes("TIMEOUT") || code.includes("STALE")) {
    return "响应时间较长，本次操作未能完成，请稍后重新尝试。";
  }
  if (
    code.includes("UNAVAILABLE") ||
    code.includes("PROVIDER") ||
    code.includes("RUNTIME") ||
    code.includes("ADAPTER") ||
    code.includes("CREDENTIAL") ||
    code.includes("QUEUE")
  ) {
    return "当前服务暂不可用，请稍后重新尝试。";
  }
  if (code.includes("INVALID_RESPONSE") || code.includes("INTERNAL")) {
    return "本次处理未能完成，请重新尝试。";
  }
  if (problem.status === 409) return "内容刚刚发生变化，请刷新后再操作。";
  if (problem.status === 422 || problem.status === 400) {
    return "提交的信息有误，请检查后重新提交。";
  }
  if (problem.status !== undefined && problem.status >= 500) {
    return "当前服务暂不可用，请稍后重新尝试。";
  }
  return "当前操作未能完成，请稍后重新尝试。";
}

export function safeLocalProductMessage(
  message: string,
  fallback = "当前操作未能完成，请稍后重新尝试。",
) {
  const normalized = message.trim();
  if (!normalized || !/[\u3400-\u9fff]/u.test(normalized)) return fallback;
  if (forbiddenTechnicalMessage.test(normalized) || internalChineseMessage.test(normalized)) {
    return fallback;
  }
  return normalized;
}

const validationFieldLabels: Readonly<Record<string, string>> = Object.freeze({
  phone: "手机号",
  nickname: "昵称",
  sms_code: "短信验证码",
  password: "密码",
  new_password: "新密码",
  password_confirmation: "确认密码",
  name: "名称",
  url: "网址",
});

const validationCodeMessages: Readonly<Record<string, string>> = Object.freeze({
  blank: "请填写此项。",
  required: "请填写此项。",
  invalid: "填写内容不正确，请检查。",
  password_too_common: "密码过于简单，请增加长度并组合数字、字母和符号。",
  password_too_short: "密码长度不足，请设置更长的密码。",
  password_entirely_numeric: "密码不能只包含数字。",
  unique: "该内容已存在，请更换后再试。",
});

export function userFacingValidationMessage(field: string, issueCode?: string) {
  const known = issueCode ? validationCodeMessages[issueCode] : undefined;
  if (known) return known;
  const label = validationFieldLabels[field] ?? "此项内容";
  return `${label}填写有误，请检查后重新提交。`;
}
