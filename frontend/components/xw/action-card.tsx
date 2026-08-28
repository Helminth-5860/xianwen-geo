import type { ReactNode } from "react";

import styles from "./xw-components.module.css";
import { XwDataStateView } from "./data-state";
import type { XwDataState, XwLinkAction, XwStateMessages, XwTone } from "./types";

export interface ActionCardProps {
  title: string;
  description?: string;
  eyebrow?: string;
  icon?: ReactNode;
  action?: XwLinkAction;
  tone?: XwTone;
  state?: XwDataState;
  messages?: XwStateMessages;
  className?: string;
}

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function ActionCard({
  title,
  description,
  eyebrow,
  icon,
  action,
  tone = "primary",
  state = "ready",
  messages,
  className,
}: ActionCardProps) {
  return (
    <article className={joinClassNames(styles.actionCard, className)} data-tone={tone}>
      <XwDataStateView
        state={state}
        compact
        loading={messages?.loading ?? "正在准备下一步…"}
        empty={messages?.empty ?? "暂时没有待处理事项"}
        error={messages?.error ?? "内容暂时无法显示，请稍后再试。"}
      >
        <div className={styles.actionCardMain}>
          {icon ? (
            <span className={styles.actionCardIcon} aria-hidden="true">
              {icon}
            </span>
          ) : null}
          <div className={styles.actionCardCopy}>
            {eyebrow ? <p>{eyebrow}</p> : null}
            <h3>{title}</h3>
            {description ? <span>{description}</span> : null}
          </div>
          {action ? (
            <a
              className={styles.actionCardLink}
              href={action.href}
              aria-label={action.accessibleLabel}
            >
              {action.label}
              <span aria-hidden="true" />
            </a>
          ) : null}
        </div>
      </XwDataStateView>
    </article>
  );
}
