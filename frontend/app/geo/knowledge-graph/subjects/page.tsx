"use client";

import { ExportOutlined } from "@ant-design/icons";
import { Pagination, Typography } from "antd";
import { useMemo, useState } from "react";

import styles from "./page.module.css";

const { Text, Title } = Typography;

const PAGE_SIZE = 20;

const platforms = [
  { name: "国家企业信用信息公示系统", url: "https://www.gsxt.gov.cn" },
  { name: "企查查", url: "https://www.qcc.com" },
  { name: "天眼查", url: "https://www.tianyancha.com" },
  { name: "爱企查", url: "https://aiqicha.baidu.com" },
  { name: "启信宝", url: "https://www.qixin.com" },
  { name: "水滴信用", url: "https://www.shuidi.cn" },
  { name: "企查猫", url: "https://www.qichamao.com" },
  { name: "88查", url: "https://88cha.com" },
  { name: "商商查", url: "https://www.shangshangcha.com" },
  { name: "企知道", url: "https://www.qizhidao.com" },
  { name: "企百科", url: "https://www.qibook.com" },
  { name: "名录集", url: "https://mingluji.com" },
  { name: "黄页88网", url: "https://b2b.huangye88.com" },
  { name: "顺企网", url: "https://www.11467.com" },
  { name: "利酷搜黄页网", url: "https://www.likuso.com" },
  { name: "万国企业网", url: "https://www.trustexporter.com" },
  { name: "中国黄页网", url: "https://www.chinayp.net" },
  { name: "1688（阿里巴巴国内站）", url: "https://www.1688.com" },
  { name: "慧聪网", url: "https://www.hc360.com" },
  { name: "中国制造网", url: "https://www.made-in-china.com" },
  { name: "阿里巴巴国际站", url: "https://www.alibaba.com" },
  { name: "环球资源", url: "https://www.globalsources.com" },
  { name: "敦煌网", url: "https://www.dhgate.com" },
  { name: "国联资源网", url: "https://www.ibicn.com" },
  { name: "金泉网", url: "https://www.jqw.com" },
  { name: "企+", url: "https://qijia.com" },
  { name: "企名片", url: "https://qimingpian.com" },
  { name: "易登网", url: "https://edeng.cn" },
  { name: "企业大黄页", url: "https://qy6.com" },
  { name: "中国114黄页", url: "https://114chn.com" },
  { name: "八方资源网", url: "https://b2b168.net" },
  { name: "亿商网", url: "https://eb80.com" },
  { name: "阿土伯", url: "https://atobo.com.cn" },
  { name: "蜘蛛商务网", url: "https://zhizhu35.com" },
  { name: "中国供应商", url: "https://china.cn" },
] as const;

function logoSources(url: string) {
  const domain = new URL(url).hostname;
  return [
    `${new URL(url).origin}/favicon.ico`,
    `https://favicon.im/${domain}?larger=true`,
  ];
}

function PlatformLogo({ name, url }: { name: string; url: string }) {
  const [sourceIndex, setSourceIndex] = useState(0);
  const sources = useMemo(() => logoSources(url), [url]);

  if (sourceIndex >= sources.length) {
    return <span className={styles.logoFallback}>{name.slice(0, 2)}</span>;
  }

  return (
    <img
      className={styles.logoImage}
      src={sources[sourceIndex]}
      alt={`${name} 标志`}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setSourceIndex((value) => value + 1)}
    />
  );
}

export default function SubjectEntityDirectoryPage() {
  const [page, setPage] = useState(1);
  const visiblePlatforms = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return platforms.slice(start, start + PAGE_SIZE);
  }, [page]);

  return (
    <main className={styles.page}>
      <section className={styles.header}>
        <div>
          <Text type="secondary">知识图谱建设</Text>
          <Title level={2}>主体实体建设</Title>
          <Text type="secondary">企业信息查询与企业名录平台</Text>
        </div>
        <Text type="secondary">共 {platforms.length} 个平台</Text>
      </section>

      <section className={styles.grid} aria-label="主体实体建设平台列表">
        {visiblePlatforms.map((platform) => (
          <article className={styles.card} key={platform.name}>
            <div className={styles.logoWrap}>
              <PlatformLogo name={platform.name} url={platform.url} />
            </div>
            <a
              className={styles.nameLink}
              href={platform.url}
              target="_blank"
              rel="noreferrer noopener"
              title={`打开 ${platform.name}`}
            >
              <span>{platform.name}</span>
              <ExportOutlined />
            </a>
          </article>
        ))}
      </section>

      {platforms.length > PAGE_SIZE && (
        <div className={styles.pagination}>
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={platforms.length}
            showSizeChanger={false}
            onChange={setPage}
          />
        </div>
      )}
    </main>
  );
}
