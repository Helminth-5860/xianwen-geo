import type { HTMLAttributes, ReactNode } from "react";

import styles from "./xw-components.module.css";
import type { XwSurfaceLevel } from "./types";

export interface GlassSurfaceProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  as?: "div" | "section" | "article" | "aside";
  level?: XwSurfaceLevel;
  interactive?: boolean;
}

function joinClassNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

export function GlassSurface({
  children,
  as: Component = "section",
  level = "soft",
  interactive = false,
  className,
  ...rest
}: GlassSurfaceProps) {
  return (
    <Component
      className={joinClassNames(
        styles.glassSurface,
        level === "strong" && styles.glassStrong,
        level === "ai" && styles.glassAi,
        interactive && styles.glassInteractive,
        className,
      )}
      {...rest}
    >
      {children}
    </Component>
  );
}
