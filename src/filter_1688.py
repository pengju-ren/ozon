"""
1688 图搜结果相关性过滤

用 Ozon 商品的标题关键词 + 品牌 + 类目来过滤 1688 图搜结果，
把不相关的（如笔记本搜出端子）过滤掉，避免后续无效计算。
"""
import re
import logging
from typing import List, Dict, Set

logger = logging.getLogger(__name__)

# 1688 结果中常见的无意义词（匹配不到任何关键信息时加分用）
_STOP_WORDS = {
    "跨境", "货源", "一件代发", "现货", "批发", "厂家", "直销", "供应",
    "热卖", "爆款", "新款", "促销", "特价", "包邮", "定制", "加工",
    "适用于", "适用", "通用", "专用", "配件", "原装", "正品",
}


class ResultFilter:
    """根据 Ozon 商品信息过滤 1688 结果"""

    def __init__(self, title_keywords: List[str], brand: str = "",
                 category_cn: str = ""):
        """
        title_keywords: 从俄语标题 + 翻译结果提取的关键词列表
        brand: 品牌名
        category_cn: 类目中文部分
        """
        self.keywords: Set[str] = set(k.lower() for k in title_keywords if k)
        self.brand = brand.strip().lower() if brand else ""
        self.category_cn = category_cn.strip()

        # 从类目提取额外关键词
        if self.category_cn:
            for w in re.split(r'[/\s、，,]+', self.category_cn):
                w = w.strip()
                if len(w) >= 2:
                    self.keywords.add(w.lower())

        # 品牌也是一个强关键词
        if self.brand:
            self.keywords.add(self.brand)

        # 去掉停用词
        self.keywords = {k for k in self.keywords if k not in _STOP_WORDS and len(k) >= 2}

        logger.debug(f"过滤关键词 ({len(self.keywords)}): {self.keywords}")

    def score(self, result_title: str) -> int:
        """
        计算 1688 结果与 Ozon 商品的相关性分数

        返回: 匹配到的关键词数量（0 = 不相关）
        """
        title_lower = result_title.lower()
        score = 0

        for kw in self.keywords:
            if kw in title_lower:
                # 长关键词权重更高
                score += 1 + (len(kw) // 4)

        # 品牌精确命中加分
        if self.brand and self.brand in title_lower:
            score += 3

        return score

    def filter(self, products: List[Dict], min_score: int = 1) -> List[Dict]:
        """
        过滤 product dict 列表
        product dict 需包含 "title" 字段

        返回: (过滤后的列表, 被过滤掉的列表) 的 tuple
        """
        passed = []
        rejected = []

        for p in products:
            title = p.get("title", "") or p.get("data", {}).get("title", "")
            s = self.score(title)
            if s >= min_score:
                p["_relevance_score"] = s
                passed.append(p)
            else:
                rejected.append(p)

        # 按分数降序
        passed.sort(key=lambda x: x.get("_relevance_score", 0), reverse=True)

        logger.info(
            f"过滤: {len(passed)} 通过 / {len(rejected)} 淘汰 "
            f"(阈值={min_score})"
        )
        return passed, rejected

    @classmethod
    def from_ozon_row(cls, translated_title: str, brand: str,
                      category: str) -> "ResultFilter":
        """
        从 Ozon 数据行创建过滤器

        translated_title: 翻译后的中文标题（或为空）
        brand: 品牌字段
        category: 类目字段（可能包含中俄双语）
        """
        from .translate_live import TitleTranslator

        # 提取关键词
        keywords = TitleTranslator.extract_keywords(
            russian_title="",  # 不从俄语提取，用翻译结果
            brand=brand,
            category=category,
        )

        # 从翻译标题追加中文关键词
        if translated_title:
            # 简单按空格和符号切分
            cn_words = re.findall(r'[一-鿿㐀-䶿]{2,}', translated_title)
            keywords.extend(cn_words)
            # 也保留拉丁词
            latin = re.findall(r'[A-Za-z0-9+\-]{3,}', translated_title)
            keywords.extend(latin)

        # 取类目第一行中文
        cat_cn = ""
        if category:
            lines = category.strip().split("\n")
            cat_cn = lines[0].strip() if lines else ""

        return cls(
            title_keywords=keywords,
            brand=brand,
            category_cn=cat_cn,
        )
