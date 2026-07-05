"""
搜索器统一接口 — 3 种 1688 搜索途径的公共基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Product1688:
    """1688 商品信息（所有后端统一使用此结构）"""
    offer_id: str = ""
    title: str = ""
    price_text: str = ""       # 显示价格文本 "¥15.00-28.00"
    price_low: float = 0.0     # 最低价（元）
    price_high: float = 0.0    # 最高价（元）
    min_order: str = ""        # 起批量
    shop_name: str = ""        # 店铺名
    location: str = ""         # 所在地/发货地
    detail_url: str = ""       # 商品详情页链接
    image_url: str = ""        # 商品主图
    sales: int = 0             # 30天销量
    similarity: float = 0.0    # 相似度（图片搜索有）
    one_stop: bool = False     # 是否支持一件代发

    @property
    def display_price(self) -> str:
        """格式化价格"""
        if self.price_low == self.price_high:
            return f"¥{self.price_low:.2f}" if self.price_low > 0 else "-"
        return f"¥{self.price_low:.2f}-{self.price_high:.2f}"

    @property
    def price_range_yuan(self) -> str:
        """纯数字价格范围"""
        if self.price_low == self.price_high:
            return f"{self.price_low:.2f}" if self.price_low > 0 else ""
        return f"{self.price_low:.2f}-{self.price_high:.2f}"


class BaseSearcher(ABC):
    """
    1688 搜索器抽象基类
    所有后端（OneBound/Playwright/1688官方API）实现此接口
    """

    def __init__(self, name: str = "base"):
        self.name = name

    @abstractmethod
    async def search_by_image(self, image_input: str) -> List[Product1688]:
        """
        以图搜款

        Args:
            image_input: 图片URL 或 本地文件路径（后端自行处理）

        Returns:
            1688 匹配商品列表
        """
        pass

    @abstractmethod
    async def search_by_keyword(self, keyword: str) -> List[Product1688]:
        """
        关键词搜索

        Args:
            keyword: 中文搜索关键词

        Returns:
            1688 商品列表
        """
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass
