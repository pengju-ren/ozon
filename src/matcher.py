"""
匹配与评分模块 - 综合图片搜索和关键词搜索结果
去重、排序、输出最佳匹配
"""
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from .searcher_1688 import Product1688
from .config import TOP_MATCHES_PER_PRODUCT

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """单个1688匹配结果"""
    offer_id: str = ""
    title_1688: str = ""
    price_min: float = 0.0
    price_max: float = 0.0
    min_order: str = ""
    shop_name: str = ""
    detail_url: str = ""
    image_url: str = ""
    similarity: float = 0.0
    search_type: str = ""      # "image" / "keyword" / "both"
    score: float = 0.0         # 综合评分

    @property
    def display_price(self) -> str:
        if self.price_min == self.price_max:
            return f"¥{self.price_min:.2f}"
        return f"¥{self.price_min:.2f}-{self.price_max:.2f}"


@dataclass
class ProductMatch:
    """一个Ozon商品的所有1688匹配"""
    ozon_rank: int = 0
    ozon_title: str = ""
    ozon_title_cn: str = ""
    ozon_price_rub: str = ""
    ozon_price_cny: float = 0.0
    ozon_sku: str = ""
    ozon_image: str = ""
    ozon_sales: int = 0
    ozon_margin: str = ""
    brand: str = ""
    category: str = ""
    matches: List[MatchResult] = field(default_factory=list)


class Matcher:
    """
    结果匹配器 - 合并、去重、评分、排序
    """

    def __init__(self, top_n: int = TOP_MATCHES_PER_PRODUCT):
        self.top_n = top_n

    def merge_and_rank(
        self,
        image_results: List[Product1688],
        keyword_results: List[Product1688]
    ) -> List[MatchResult]:
        """
        合并图片搜索和关键词搜索结果，按综合评分排序

        Args:
            image_results: 图片搜索结果（带相似度）
            keyword_results: 关键词搜索结果

        Returns:
            排序后的匹配结果列表
        """
        # 按 offer_id 去重合并
        merged: Dict[str, MatchResult] = {}

        for item in image_results:
            if not item.offer_id:
                continue
            result = self._to_match_result(item)
            if item.offer_id in merged:
                # 合并：保留图片搜索的相似度，更新搜索类型
                existing = merged[item.offer_id]
                existing.search_type = "both"
                existing.similarity = max(existing.similarity, item.similarity)
            else:
                merged[item.offer_id] = result

        for item in keyword_results:
            if not item.offer_id:
                continue
            if item.offer_id in merged:
                merged[item.offer_id].search_type = "both"
            else:
                merged[item.offer_id] = self._to_match_result(item)

        # 计算综合评分并排序
        results = list(merged.values())
        for r in results:
            r.score = self._calculate_score(r)

        results.sort(key=lambda x: x.score, reverse=True)

        return results[:self.top_n]

    def _to_match_result(self, item: Product1688) -> MatchResult:
        """将 Product1688 转为 MatchResult"""
        return MatchResult(
            offer_id=item.offer_id,
            title_1688=item.title,
            price_min=item.price_min,
            price_max=item.price_max,
            min_order=item.min_order,
            shop_name=item.shop_name,
            detail_url=item.detail_url,
            image_url=item.image_url,
            similarity=item.similarity,
            search_type=item.search_type,
            score=0.0,
        )

    def _calculate_score(self, result: MatchResult) -> float:
        """
        综合评分算法

        权重因素:
        - 图片相似度（0-1），权重 40%
        - 搜索类型：图片匹配 > 关键词匹配，权重 25%
        - 价格合理性：有明确批发价，权重 20%
        - 店铺可信度：有一件代发标识，权重 15%
        """
        score = 0.0

        # 1. 相似度得分 (0-40分)
        score += result.similarity * 40

        # 2. 搜索类型得分 (0-25分)
        if result.search_type == "both":
            score += 25
        elif result.search_type == "image":
            score += 20
        else:
            score += 10

        # 3. 价格得分 (0-20分) — 有明确价格即可
        if result.price_min > 0:
            score += 20
        elif result.price_max > 0:
            score += 15

        # 4. 店铺信息得分 (0-15分)
        if result.shop_name:
            score += 10
        if result.min_order:
            score += 5

        return round(score, 2)

    @staticmethod
    def estimate_profit_margin(ozon_price_cny: float, cost_price: float) -> str:
        """估算毛利率"""
        if ozon_price_cny <= 0 or cost_price <= 0:
            return "N/A"
        margin = (ozon_price_cny - cost_price) / ozon_price_cny * 100
        return f"{margin:.1f}%"
