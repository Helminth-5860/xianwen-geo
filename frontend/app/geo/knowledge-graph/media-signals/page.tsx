"use client";

/* eslint-disable @next/next/no-img-element -- favicon hosts are dynamic and cannot use a fixed Next Image allowlist. */
import { ExportOutlined, SearchOutlined } from "@ant-design/icons";
import { Empty, Input, Pagination, Tag, Typography } from "antd";
import { useMemo, useState } from "react";

import { mediaSignalItems, type MediaSignalItem } from "./data";
import styles from "./page.module.css";

const { Text, Title } = Typography;

const PAGE_SIZE = 20;

function faviconSources(item: MediaSignalItem) {
  const automaticSources = [
    `https://www.google.com/s2/favicons?sz=128&domain_url=${encodeURIComponent(item.url)}`,
    `${new URL(item.url).origin}/favicon.ico`,
    `https://favicon.im/${item.domain}?larger=true`,
  ];
  return item.logo ? [item.logo, ...automaticSources] : automaticSources;
}

function MediaLogo({ item }: Readonly<{ item: MediaSignalItem }>) {
  const [sourceIndex, setSourceIndex] = useState(0);
  const sources = faviconSources(item);

  if (sourceIndex >= sources.length) {
    return (
      <span className={styles.logoFallback} aria-hidden="true">
        {item.name.slice(0, 1)}
      </span>
    );
  }

  return (
    <img
      className={styles.logoImage}
      src={sources[sourceIndex]}
      alt=""
      aria-hidden="true"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setSourceIndex((value) => value + 1)}
    />
  );
}

export default function MediaSignalsDirectoryPage() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const filteredItems = useMemo(() => {
    if (!normalizedQuery) return mediaSignalItems;
    return mediaSignalItems.filter(
      (item) =>
        item.name.toLocaleLowerCase("zh-CN").includes(normalizedQuery) ||
        item.domain.toLocaleLowerCase("en-US").includes(normalizedQuery),
    );
  }, [normalizedQuery]);
  const visibleItems = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return filteredItems.slice(start, start + PAGE_SIZE);
  }, [filteredItems, page]);

  return (
    <main className={styles.page}>
      <section className={styles.header}>
        <div>
          <Text type="secondary">KNOWLEDGE GRAPH</Text>
          <Title level={2}>媒体信号建设</Title>
          <Text type="secondary">全网自媒体与官方媒体资源目录</Text>
        </div>
        <Text type="secondary">共 {mediaSignalItems.length} 家媒体</Text>
      </section>

      <section className={styles.searchBar} aria-label="媒体目录搜索">
        <Input
          className={styles.searchInput}
          value={query}
          prefix={<SearchOutlined aria-hidden="true" />}
          placeholder="搜索媒体名称或域名"
          aria-label="搜索媒体名称或域名"
          allowClear
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(1);
          }}
        />
        <Text type="secondary" aria-live="polite">
          {normalizedQuery ? `找到 ${filteredItems.length} 家媒体` : "支持媒体名称与域名模糊搜索"}
        </Text>
      </section>

      {visibleItems.length > 0 ? (
        <section className={styles.grid} aria-label="媒体信号资源列表">
          {visibleItems.map((item) => (
            <a
              className={styles.card}
              key={item.id}
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`打开 ${item.name} 官网`}
            >
              <span className={styles.logoWrap}>
                <MediaLogo item={item} />
              </span>
              <span className={styles.cardContent}>
                <span className={styles.nameRow}>
                  <span className={styles.mediaName}>{item.name}</span>
                  <ExportOutlined aria-hidden="true" />
                </span>
                <span className={styles.domain} title={item.domain}>
                  {item.domain}
                </span>
                <span className={styles.metadata}>
                  {item.level ? <Tag color="blue">{item.level} 级</Tag> : null}
                  {item.category ? <span>{item.category}</span> : null}
                </span>
              </span>
            </a>
          ))}
        </section>
      ) : (
        <section className={styles.emptyState} aria-live="polite">
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到匹配的媒体" />
        </section>
      )}

      {filteredItems.length > PAGE_SIZE ? (
        <div className={styles.pagination}>
          <Pagination
            aria-label="媒体目录分页"
            current={page}
            pageSize={PAGE_SIZE}
            total={filteredItems.length}
            showSizeChanger={false}
            onChange={setPage}
          />
        </div>
      ) : null}
    </main>
  );
}
