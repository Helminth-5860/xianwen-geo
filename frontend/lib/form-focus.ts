import type { FormInstance, FormProps } from "antd";

export function focusFirstInvalidField(
  form: FormInstance,
): NonNullable<FormProps["onFinishFailed"]> {
  return ({ errorFields }) => {
    const fieldName = errorFields[0]?.name;
    if (!fieldName) return;
    form.scrollToField(fieldName, { block: "center" });
    window.requestAnimationFrame(() => {
      const field = form.getFieldInstance(fieldName) as { focus?: () => void } | undefined;
      field?.focus?.();
    });
  };
}
