"use client";

import { Segmented, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import type {
  WebsiteContact,
  WebsitePage,
  WebsiteProject,
  WebsiteSection,
} from "@/lib/websites-client";

import styles from "./website-draft-preview.module.css";

export type WebsitePreviewImage = Readonly<{
  id: string;
  url: string;
  name: string;
  source: "客户上传" | "内容图片库";
}>;

type Props = Readonly<{
  project: WebsiteProject;
  subjectName: string;
  materials: WebsitePreviewImage[];
}>;

const contactLabels: Readonly<Record<keyof WebsiteContact, string>> = {
  brand_name: "品牌名称",
  primary_business: "主营业务",
  business_address: "联系地址",
  contact_name: "联系人",
  contact_phone: "联系电话",
};

function styleClass(styleKey: WebsiteProject["style_key"]) {
  if (styleKey === "technology") return styles.technology;
  if (styleKey === "premium") return styles.premium;
  return "";
}

function SectionView({
  section,
  index,
  contact,
  images,
}: Readonly<{
  section: WebsiteSection;
  index: number;
  contact: WebsiteContact;
  images: WebsitePreviewImage[];
}>) {
  if (section.type === "faq") {
    return (
      <section className={`${styles.section} ${index % 2 ? styles.sectionAlt : ""}`}>
        {section.title && <h2 className={styles.sectionTitle}>{section.title}</h2>}
        {section.body && <p className={styles.sectionBody}>{section.body}</p>}
        <div className={styles.faqList}>
          {section.items.map((item, itemIndex) => (
            <div className={styles.faqItem} key={`${item.title}-${itemIndex}`}>
              <p className={styles.faqQuestion}>{item.title}</p>
              <p className={styles.cardBody}>{item.body}</p>
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (section.type === "contact") {
    const contactEntries = (Object.keys(contactLabels) as Array<keyof WebsiteContact>).flatMap(
      (key) => {
        const value = contact[key];
        return typeof value === "string" && value.trim() ? [[key, value.trim()] as const] : [];
      },
    );
    return (
      <section className={`${styles.section} ${index % 2 ? styles.sectionAlt : ""}`}>
        {section.title && <h2 className={styles.sectionTitle}>{section.title}</h2>}
        {section.body && <p className={styles.sectionBody}>{section.body}</p>}
        {contactEntries.length > 0 && (
          <div className={styles.contactGrid}>
            {contactEntries.map(([key, value]) => (
              <div className={styles.contactItem} key={key}>
                <span className={styles.contactLabel}>{contactLabels[key]}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        )}
      </section>
    );
  }

  if (section.type === "cards") {
    return (
      <section className={`${styles.section} ${index % 2 ? styles.sectionAlt : ""}`}>
        {section.title && <h2 className={styles.sectionTitle}>{section.title}</h2>}
        {section.body && <p className={styles.sectionBody}>{section.body}</p>}
        <div className={styles.cards}>
          {section.items.map((item, itemIndex) => {
            const image = images.length ? images[(index + itemIndex) % images.length] : null;
            return (
              <article className={styles.card} key={`${item.title}-${itemIndex}`}>
                {image?.url && (
                  // Signed private-media URLs are issued by the existing backend.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className={styles.cardImage} src={image.url} alt={item.title} />
                )}
                <div className={styles.cardCopy}>
                  <h3 className={styles.cardTitle}>{item.title}</h3>
                  <p className={styles.cardBody}>{item.body}</p>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    );
  }

  return (
    <section className={`${styles.section} ${index % 2 ? styles.sectionAlt : ""}`}>
      {section.title && <h2 className={styles.sectionTitle}>{section.title}</h2>}
      {section.body && <p className={styles.sectionBody}>{section.body}</p>}
      {section.items.length > 0 && (
        <div className={styles.cards}>
          {section.items.map((item, itemIndex) => (
            <article className={styles.card} key={`${item.title}-${itemIndex}`}>
              <div className={styles.cardCopy}>
                <h3 className={styles.cardTitle}>{item.title}</h3>
                <p className={styles.cardBody}>{item.body}</p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function PagePreview({
  page,
  project,
  subjectName,
  materials,
  onNavigate,
}: Readonly<{
  page: WebsitePage;
  project: WebsiteProject;
  subjectName: string;
  materials: WebsitePreviewImage[];
  onNavigate: (key: WebsitePage["key"]) => void;
}>) {
  const heroIndex = page.sections.findIndex((section) => section.type === "hero");
  const hero = page.sections[heroIndex >= 0 ? heroIndex : 0];
  const remaining = page.sections.filter((_, index) => index !== (heroIndex >= 0 ? heroIndex : 0));
  const heroImage = materials[0];
  const cardImages = materials.slice(1);

  return (
    <>
      <header className={styles.siteNav}>
        <span className={styles.brand}>{subjectName}</span>
        <nav className={styles.navLinks} aria-label="官网草稿页面导航">
          {project.site?.pages.map((item) => (
            <button
              type="button"
              className={`${styles.navLink} ${item.key === page.key ? styles.navLinkActive : ""}`}
              key={item.key}
              onClick={() => onNavigate(item.key)}
            >
              {item.title}
            </button>
          ))}
        </nav>
      </header>

      {hero && (
        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <span className={styles.eyebrow}>围绕企业真实资料生成</span>
            <h1 className={styles.heroTitle}>{hero.title || page.title}</h1>
            <p className={styles.heroBody}>{hero.body || project.site?.tagline}</p>
          </div>
          {heroImage?.url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className={styles.heroImage} src={heroImage.url} alt={`${page.title}主视觉`} />
          ) : (
            <div className={styles.heroVisualFallback} aria-hidden="true" />
          )}
        </section>
      )}

      {remaining.map((section, index) => (
        <SectionView
          key={`${section.type}-${index}`}
          section={section}
          index={index}
          contact={project.contact}
          images={cardImages}
        />
      ))}

      <footer className={styles.footer}>
        {subjectName} · 官网草稿预览 · 内容依据当前主体已确认资料生成
      </footer>
    </>
  );
}

export function WebsiteDraftPreview({ project, subjectName, materials }: Props) {
  const pages = project.site?.pages ?? [];
  const [device, setDevice] = useState<"电脑预览" | "手机预览">("电脑预览");
  const [activePageKey, setActivePageKey] = useState<WebsitePage["key"]>("home");

  useEffect(() => {
    if (pages.length && !pages.some((page) => page.key === activePageKey)) {
      setActivePageKey(pages[0].key);
    }
  }, [activePageKey, pages]);

  const activePage = pages.find((page) => page.key === activePageKey) ?? pages[0];
  if (!activePage) return null;

  return (
    <div className={styles.previewShell}>
      <div className={styles.toolbar}>
        <Space wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            官网预览
          </Typography.Title>
          <Tag color="blue">草稿</Tag>
          <Typography.Text type="secondary">不会自动公开，确认后再进入发布流程</Typography.Text>
        </Space>
        <Space wrap>
          <Segmented
            value={activePage.key}
            options={pages.map((page) => ({ label: page.title, value: page.key }))}
            onChange={(value) => setActivePageKey(value as WebsitePage["key"])}
          />
          <Segmented
            value={device}
            options={["电脑预览", "手机预览"]}
            onChange={(value) => setDevice(value as "电脑预览" | "手机预览")}
          />
        </Space>
      </div>

      <div className={styles.frameWrap}>
        <div
          className={`${styles.frame} ${device === "手机预览" ? styles.frameMobile : ""} ${styleClass(project.style_key)}`}
        >
          <PagePreview
            page={activePage}
            project={project}
            subjectName={subjectName}
            materials={materials}
            onNavigate={setActivePageKey}
          />
        </div>
      </div>
    </div>
  );
}
