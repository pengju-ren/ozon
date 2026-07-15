"""
DeepSeek LLM — 翻译 + 相关性过滤

用 LLM 替代关键词匹配：
  1. 翻译：俄语标题 → 电商中文
  2. 过滤：Ozon 商品信息 + 1688 搜索结果 → LLM 打分
"""
import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from dotenv import load_dotenv
from openai import OpenAI

# 加载项目根目录 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

# DeepSeek API
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if not api_key:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY，请检查 .env")
        _client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"DeepSeek client 初始化: {base_url}")
    return _client


# ------------------------------------------------------------------
# 翻译
# ------------------------------------------------------------------
TRANSLATE_PROMPT = """你是俄语电商标题翻译专家。将以下 Ozon 俄语标题翻译成中文电商标题。

规则:
- 保留所有英文品牌名、型号名（如 ASUS, ROG, AMD, Ryzen, Intel, DJI, EcoFlow 等）
- 保留数字和规格（如 64GB, 3600W, 20л → 20L）
- 俄语部分翻译成中文
- 最终结果只要中文翻译，不要解释

俄语标题: {title}
"""


def translate_title(title_ru: str) -> str:
    """LLM 翻译俄语标题 → 中文"""
    if not title_ru or not title_ru.strip():
        return ""

    # 如果几乎全是英文/数字，直接返回
    cyrillic = sum(1 for c in title_ru if 'А' <= c <= 'я' or c in 'Ёё')
    if cyrillic < 5:
        return title_ru

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": TRANSLATE_PROMPT.format(title=title_ru)}],
            temperature=0.1,
            max_tokens=200,
        )
        result = resp.choices[0].message.content.strip()
        logger.debug(f"翻译: {title_ru[:60]} → {result[:60]}")
        return result
    except Exception as e:
        logger.warning(f"翻译失败: {e}")
        return title_ru


# ------------------------------------------------------------------
# 批量过滤
# ------------------------------------------------------------------
FILTER_PROMPT = """你是电商选品匹配专家。给定一个 Ozon 商品和一批 1688 搜索结果，判断每个 1688 结果是否是该 Ozon 商品的**同款或高度相关替代品**。

## Ozon 商品信息
- 俄语标题: {title_ru}
- 中文翻译: {title_cn}
- 品牌: {brand}
- 类目: {category}
- 售价: {price_rub}

## 1688 搜索结果（共 {total} 条）
{results_text}

## 评分标准
- 10 分: 同款，品牌/型号/规格完全一致
- 7-9 分: 同品类，高度相关（如同款保护膜、同款配件）
- 4-6 分: 相关品类（如同一产品类型的其他品牌/型号）
- 1-3 分: 弱相关（仅是同一大类，如电子 vs 电脑配件）
- 0 分: 完全无关

## 输出格式
返回 JSON 数组，只包含 offerId 和分数：
```json
[
  {{"offerId": "xxx", "score": 8, "reason": "华硕ROG专用保护膜，高度相关"}},
  ...
]
```

只输出 JSON，不要其他文字。"""


def filter_by_llm(ozon_info: Dict, results: List[Dict],
                  top_n: int = 20) -> List[Dict]:
    """
    用 LLM 批量打分 1688 搜索结果

    ozon_info: {"title_ru", "title_cn", "brand", "category", "price_rub"}
    results: H5 API 原始搜索结果列表
    top_n: 返回前 N 个最高分

    返回: 带 _llm_score 的 results
    """
    if not results:
        return []

    # 构建结果文本（每条一行，编号）
    lines = []
    for i, item in enumerate(results):
        d = item.get("data", {}) if isinstance(item, dict) else {}
        title = d.get("title", item.get("title", ""))
        price = d.get("priceInfo", {}).get("price", "") if isinstance(d.get("priceInfo"), dict) else ""
        shop = d.get("shopAddition", {}).get("text", "") if isinstance(d.get("shopAddition"), dict) else ""
        offer_id = d.get("offerId", "")
        lines.append(f"[{i}] offerId={offer_id} | {title} | ¥{price} | {shop}")

    results_text = "\n".join(lines)

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{
                "role": "user",
                "content": FILTER_PROMPT.format(
                    title_ru=ozon_info.get("title_ru", ""),
                    title_cn=ozon_info.get("title_cn", ""),
                    brand=ozon_info.get("brand", "-"),
                    category=ozon_info.get("category", "-"),
                    price_rub=ozon_info.get("price_rub", "-"),
                    total=len(results),
                    results_text=results_text,
                )
            }],
            temperature=0.1,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content.strip()

        # 解析 JSON
        scores = _parse_llm_json(raw)
        logger.info(f"LLM 过滤: {len(scores)} 条有分数")

    except Exception as e:
        logger.warning(f"LLM 过滤失败: {e}，回退到关键词过滤")
        # 回退：用分数 0
        scores = []

    # 把分数写回 results
    score_map = {s["offerId"]: s for s in scores}
    for item in results:
        d = item.get("data", {}) if isinstance(item, dict) else {}
        oid = d.get("offerId", "")
        matched = score_map.get(oid, {})
        item["_llm_score"] = matched.get("score", 0)
        item["_llm_reason"] = matched.get("reason", "")

    # 过滤 + 排序
    filtered = [r for r in results if r.get("_llm_score", 0) >= 4]  # ≥4 分通过
    filtered.sort(key=lambda x: x.get("_llm_score", 0), reverse=True)

    logger.info(
        f"LLM 过滤: {len(filtered)} 通过 / {len(results) - len(filtered)} 淘汰 "
        f"(阈值=4)"
    )
    return filtered[:top_n]


def _parse_llm_json(raw: str) -> List[Dict]:
    """解析 LLM 返回的 JSON"""
    # 去掉 markdown 包裹
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 尝试逐行提取
        import re
        scores = []
        for m in re.finditer(
            r'"offerId"\s*:\s*"(\d+)"[^}]*"score"\s*:\s*(\d+)',
            raw
        ):
            scores.append({"offerId": m.group(1), "score": int(m.group(2))})
        return scores


# ------------------------------------------------------------------
# 便捷入口
# ------------------------------------------------------------------
def translate_and_filter(ozon_row: Dict, search_results: List[Dict],
                         top_n: int = 20) -> Tuple[str, List[Dict]]:
    """
    一条龙: 翻译标题 + LLM 过滤

    ozon_row: CSV 行 dict
    search_results: H5 图搜结果

    返回: (中文标题, 过滤后的结果列表)
    """
    title_ru = (ozon_row.get("标题") or "").strip()
    brand = (ozon_row.get("品牌") or "").strip()
    category = (ozon_row.get("类目") or "").strip()

    # 1. 翻译
    title_cn = translate_title(title_ru)

    # 2. 过滤
    ozon_info = {
        "title_ru": title_ru,
        "title_cn": title_cn,
        "brand": brand,
        "category": category,
        "price_rub": (ozon_row.get("售价") or "").strip(),
    }
    filtered = filter_by_llm(ozon_info, search_results, top_n=top_n)

    return title_cn, filtered
