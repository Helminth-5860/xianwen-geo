"use client";

export default function GlobalApplicationError({ reset }: Readonly<{ reset: () => void }>) {
  return (
    <html lang="zh-CN">
      <body>
        <main
          style={{
            display: "grid",
            minHeight: "100vh",
            placeItems: "center",
            padding: 24,
            textAlign: "center",
          }}
        >
          <div>
            <h1>页面暂时无法打开</h1>
            <p>你的数据不会受到影响，可以重新尝试或返回工作台。</p>
            <div style={{ display: "flex", justifyContent: "center", gap: 12 }}>
              <button type="button" onClick={reset}>
                重新尝试
              </button>
              <a href="/workspace">返回工作台</a>
            </div>
          </div>
        </main>
      </body>
    </html>
  );
}
