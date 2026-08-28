from dataclasses import dataclass


@dataclass(frozen=True)
class BuiltinAIModel:
    provider_key: str
    provider_name: str
    model_key: str
    display_name: str
    canonical_order: int


@dataclass(frozen=True)
class BuiltinAPIService:
    provider_key: str
    provider_name: str


BUILTIN_AI_MODELS = (
    BuiltinAIModel("deepseek", "DeepSeek", "deepseek", "DeepSeek", 10),
    BuiltinAIModel("doubao", "豆包", "doubao", "豆包", 20),
    BuiltinAIModel("qwen", "通义千问", "qwen", "通义千问", 30),
    BuiltinAIModel("hunyuan", "腾讯混元", "hunyuan", "腾讯混元", 40),
    BuiltinAIModel("wenxin", "百度文心", "wenxin", "百度文心", 50),
    BuiltinAIModel("kimi", "Kimi", "kimi", "Kimi", 60),
    BuiltinAIModel("glm", "智谱 GLM", "glm", "智谱 GLM", 70),
    BuiltinAIModel("spark", "讯飞星火", "spark", "讯飞星火", 80),
)

# Non-model provider credentials that are managed by the same encrypted credential center.
# They intentionally do not create AIModel rows and therefore do not appear in the
# model runtime table.
BUILTIN_API_SERVICES = (
    BuiltinAPIService("baidu_search", "百度搜索（信源指数）"),
)

BUILTIN_PROVIDER_KEYS = tuple(
    dict.fromkeys(
        [item.provider_key for item in BUILTIN_AI_MODELS]
        + [item.provider_key for item in BUILTIN_API_SERVICES]
    )
)
BUILTIN_MODEL_KEYS = tuple(item.model_key for item in BUILTIN_AI_MODELS)
BUILTIN_BY_MODEL_KEY = {item.model_key: item for item in BUILTIN_AI_MODELS}
