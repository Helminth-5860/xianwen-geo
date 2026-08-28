export type AIModelPresentation = Readonly<{
  name: string;
  logoPath: string | null;
}>;

const presentations: Readonly<Record<string, AIModelPresentation>> = {
  deepseek: { name: "DeepSeek", logoPath: "/model-logos/deepseek.png" },
  doubao: { name: "豆包", logoPath: "/model-logos/doubao.png" },
  qwen: { name: "通义千问", logoPath: "/model-logos/qwen.png" },
  hunyuan: { name: "腾讯混元", logoPath: "/model-logos/hunyuan.png" },
  wenxin: { name: "文心一言", logoPath: "/model-logos/wenxin.png" },
  kimi: { name: "Kimi", logoPath: "/model-logos/kimi.png" },
  glm: { name: "智谱清言", logoPath: "/model-logos/glm.png" },
  spark: { name: "讯飞星火", logoPath: "/model-logos/spark.png" },
};

export function aiModelPresentation(modelKey: string, displayName: string): AIModelPresentation {
  const known = presentations[modelKey.toLowerCase()];
  if (known) return known;
  return { name: displayName, logoPath: null };
}
