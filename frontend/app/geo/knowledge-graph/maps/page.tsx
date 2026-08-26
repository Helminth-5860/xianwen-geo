"use client";

import { ExportOutlined } from "@ant-design/icons";
import { Typography } from "antd";
import { useMemo, useState } from "react";

import styles from "../subjects/page.module.css";

const { Text, Title } = Typography;

const maps = [
  { name: "高德地图 Amap", url: "https://www.amap.com" },
  { name: "百度地图 Baidu Maps", url: "https://map.baidu.com" },
  { name: "腾讯地图 Tencent Maps", url: "https://map.qq.com" },
  { name: "天地图 MapWorld", url: "https://www.tianditu.gov.cn" },
  { name: "凯立德 Careland", url: "https://www.kldjy.com" },
  { name: "奥维互动地图 Oviital", url: "https://www.ovital.com" },
  { name: "Google Maps", url: "https://maps.google.com" },
  { name: "Apple Maps", url: "https://www.apple.com/maps" },
  { name: "Waze", url: "https://www.waze.com" },
  { name: "HERE WeGo", url: "https://wego.here.com" },
  { name: "OpenStreetMap", url: "https://www.openstreetmap.org" },
  { name: "Bing Maps", url: "https://www.bing.com/maps" },
  { name: "TomTom", url: "https://www.tomtom.com" },
  { name: "Yandex Maps", url: "https://yandex.com/maps" },
  { name: "MapQuest", url: "https://www.mapquest.com" },
  { name: "Sygic", url: "https://www.sygic.com" },
  { name: "Naver Maps", url: "https://map.naver.com" },
] as const;

function logoSources(url: string) {
  const domain = new URL(url).hostname;
  return [
    `${new URL(url).origin}/favicon.ico`,
    `https://favicon.im/${domain}?larger=true`,
  ];
}

function MapLogo({ name, url }: { name: string; url: string }) {
  const [sourceIndex, setSourceIndex] = useState(0);
  const sources = useMemo(() => logoSources(url), [url]);

  if (sourceIndex >= sources.length) {
    return <span className={styles.logoFallback}>{name.slice(0, 2)}</span>;
  }

  return (
    <img
      className={styles.logoImage}
      src={sources[sourceIndex]}
      alt={`${name} Logo`}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setSourceIndex((value) => value + 1)}
    />
  );
}

export default function MapEntityDirectoryPage() {
  return (
    <main className={styles.page}>
      <section className={styles.header}>
        <div>
          <Text type="secondary">KNOWLEDGE GRAPH</Text>
          <Title level={2}>地图实体建设</Title>
          <Text type="secondary">主流地图与导航平台</Text>
        </div>
        <Text type="secondary">共 {maps.length} 个平台</Text>
      </section>

      <section className={styles.grid} aria-label="地图实体建设平台列表">
        {maps.map((map) => (
          <article className={styles.card} key={map.name}>
            <div className={styles.logoWrap}>
              <MapLogo name={map.name} url={map.url} />
            </div>
            <a
              className={styles.nameLink}
              href={map.url}
              target="_blank"
              rel="noreferrer noopener"
              title={`打开 ${map.name}`}
            >
              <span>{map.name}</span>
              <ExportOutlined />
            </a>
          </article>
        ))}
      </section>
    </main>
  );
}
