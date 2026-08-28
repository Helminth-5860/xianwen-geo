const PHONE_PATTERN = /^1[3-9]\d{9}$/;

export function normalizedMainlandPhone(value: string): string | null {
  const compact = value.trim().replace(/[\s-]+/g, "");
  const national = compact.startsWith("+86")
    ? compact.slice(3)
    : compact.startsWith("0086")
      ? compact.slice(4)
      : compact;
  return PHONE_PATTERN.test(national) ? national : null;
}

export function validatePhone(value: string): Promise<void> {
  return normalizedMainlandPhone(value)
    ? Promise.resolve()
    : Promise.reject(new Error("请输入有效的中国大陆手机号"));
}

export function validatePassword(value: string): Promise<void> {
  if (!value || value.length < 10) {
    return Promise.reject(new Error("密码至少需要 10 个字符"));
  }
  return Promise.resolve();
}

export function validateConfirmation(password: string, confirmation: string): Promise<void> {
  return password === confirmation
    ? Promise.resolve()
    : Promise.reject(new Error("两次输入的密码不一致"));
}
