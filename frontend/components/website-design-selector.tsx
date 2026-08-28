"use client";

import { Button, Card, Space, Tag, Typography } from "antd";

import type {
  WebsiteDensityKey,
  WebsiteDesignOptions,
  WebsiteDesignRecommendation,
  WebsiteStyleKey,
  WebsiteThemeKey,
} from "@/lib/websites-client";

import styles from "./website-builder-workspace.module.css";

const themeSwatches: Readonly<Record<WebsiteThemeKey, string>> = {
  ocean: "linear-gradient(135deg, #173f9f, #4f8cff)",
  obsidian: "linear-gradient(135deg, #0f141d, #6f5a35)",
  cloud: "linear-gradient(135deg, #d0d5dd, #f8fafc)",
  amethyst: "linear-gradient(135deg, #5236c6, #9c82ff)",
  jade: "linear-gradient(135deg, #0e6655, #55b89f)",
  gold: "linear-gradient(135deg, #75501d, #d7b478)",
};

type Props = Readonly<{
  options: WebsiteDesignOptions;
  recommendation: WebsiteDesignRecommendation;
  styleKey: WebsiteStyleKey;
  themeKey: WebsiteThemeKey;
  densityKey: WebsiteDensityKey;
  disabled?: boolean;
  canSave?: boolean;
  saving?: boolean;
  onStyleChange: (value: WebsiteStyleKey) => void;
  onThemeChange: (value: WebsiteThemeKey) => void;
  onDensityChange: (value: WebsiteDensityKey) => void;
  onSave?: () => void;
}>;

export function WebsiteDesignSelector({
  options,
  recommendation,
  styleKey,
  themeKey,
  densityKey,
  disabled = false,
  canSave = false,
  saving = false,
  onStyleChange,
  onThemeChange,
  onDensityChange,
  onSave,
}: Props) {
  const recommendedThemes = new Set(options.recommended_themes[styleKey] ?? []);
  const recommendedCombination =
    styleKey === recommendation.style_key &&
    themeKey === recommendation.theme_key &&
    densityKey === recommendation.density_key;

  return (
    <Card>
      <div className={styles.designHeader}>
        <div>
          <Space size="small" wrap>
            <Typography.Title level={4} style={{ margin: 0 }}>
              网站设计
            </Typography.Title>
            {recommendedCombination && <Tag color="blue">显问推荐</Tag>}
          </Space>
          <Typography.Text type="secondary">
            风格决定页面布局，主题决定视觉气质，内容丰富度决定页面展示多少信息。
          </Typography.Text>
        </div>
        {canSave && onSave && (
          <Button type="primary" loading={saving} disabled={disabled} onClick={onSave}>
            保存当前设计
          </Button>
        )}
      </div>

      <div className={styles.designGroup}>
        <div className={styles.designGroupTitle}>
          <strong>网站风格</strong>
          <span>决定首屏、图片、卡片和内容区域怎么排版</span>
        </div>
        <div className={styles.styleGrid}>
          {options.styles.map((option) => (
            <button
              type="button"
              key={option.key}
              className={`${styles.styleButton} ${styleKey === option.key ? styles.styleButtonSelected : ""}`}
              aria-pressed={styleKey === option.key}
              disabled={disabled}
              onClick={() => onStyleChange(option.key)}
            >
              <span className={styles.styleName}>
                {option.name}
                {recommendation.style_key === option.key && (
                  <span className={styles.inlineRecommendation}>推荐</span>
                )}
              </span>
              <span className={styles.styleDescription}>{option.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div className={styles.designGroup}>
        <div className={styles.designGroupTitle}>
          <strong>视觉主题</strong>
          <span>六种主题可以与任意网站风格组合</span>
        </div>
        <div className={styles.themeGrid}>
          {options.themes.map((option) => (
            <button
              type="button"
              key={option.key}
              className={`${styles.themeButton} ${themeKey === option.key ? styles.themeButtonSelected : ""}`}
              aria-pressed={themeKey === option.key}
              disabled={disabled}
              onClick={() => onThemeChange(option.key)}
            >
              <span
                className={styles.themeSwatch}
                style={{ background: themeSwatches[option.key] }}
                aria-hidden="true"
              />
              <span className={styles.themeCopy}>
                <span className={styles.themeName}>
                  {option.name}
                  {recommendedThemes.has(option.key) && (
                    <span className={styles.inlineRecommendation}>推荐</span>
                  )}
                </span>
                <span className={styles.themeDescription}>{option.description}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className={styles.designGroup}>
        <div className={styles.designGroupTitle}>
          <strong>内容丰富度</strong>
          <span>切换后只改变页面展示量，不会重新生成文字内容</span>
        </div>
        <div className={styles.densityGrid}>
          {options.densities.map((option) => (
            <button
              type="button"
              key={option.key}
              className={`${styles.densityButton} ${densityKey === option.key ? styles.densityButtonSelected : ""}`}
              aria-pressed={densityKey === option.key}
              disabled={disabled}
              onClick={() => onDensityChange(option.key)}
            >
              <span className={styles.densityName}>
                {option.name}
                {recommendation.density_key === option.key && (
                  <span className={styles.inlineRecommendation}>推荐</span>
                )}
              </span>
              <span className={styles.densityDescription}>{option.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div className={styles.designHint}>
        当前选择可以直接用于生成官网。官网草稿生成后，也可以只更换设计而保留原来的文字内容。
      </div>
    </Card>
  );
}
