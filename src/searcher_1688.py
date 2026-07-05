"""
1688搜索模块 - 封装 OneBound/Open Claw API
支持关键词搜索 (item_search) 和图片搜索 (item_search_img)
"""
import time
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import requests

from .config import (
    ONEBOUND_API_KEY,
    ONEBOUND_API_SECRET,
    ONEBOUND_BASE_URL,
    PAGE_SIZE,
    SEARCH_PAGES,
    IMAGE_SIMILARITY_THRESHOLD,
    REQUEST_DELAY,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


@dataclass
class Product1688:
    """1688 商品信息"""
    offer_id: str = ""
    title: str = ""
    price: str = ""              # 批发价（可能是范围 "15.00-20.00"）
    price_min: float = 0.0       # 最低批发价（元）
    price_max: float = 0.0       # 最高批发价（元）
    min_order: str = ""          # 起批量
    shop_name: str = ""
    detail_url: str = ""
    image_url: str = ""
    sales: int = 0               # 30天销量
    similarity: float = 0.0      # 图片搜索相似度 0-1
    search_type: str = ""        # "image" 或 "keyword"
    category: str = ""
    location: str = ""           # 发货地
    one_stop_service: bool = False  # 是否一件代发

    @property
    def display_price(self) -> str:
        """格式化价格显示"""
        if self.price_min == self.price_max:
            return f"{self.price_min:.2f}元"
        return f"{self.price_min:.2f}-{self.price_max:.2f}元"


class Searcher1688:
    """1688 搜索器"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key or ONEBOUND_API_KEY
        self.api_secret = api_secret or ONEBOUND_API_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            "Accept-Encoding": "gzip",
            "Connection": "close",
        })
        self._call_count = 0

    # ================================================================
    # 关键词搜索
    # ================================================================

    def search_by_keyword(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = PAGE_SIZE,
        sort: str = "default"
    ) -> List[Product1688]:
        """
        按关键词搜索1688商品

        Args:
            keyword: 中文搜索关键词
            page: 页码
            page_size: 每页条数（最大50）
            sort: 排序方式 - default(综合), sale_desc(销量降序), price_asc(价格升序)

        Returns:
            1688商品列表
        """
        url = f"{ONEBOUND_BASE_URL}/item_search"
        params = {
            "key": self.api_key,
            "secret": self.api_secret,
            "q": keyword,
            "page": page,
            "page_size": page_size,
            "sort": sort,
        }

        data = self._request(url, params)
        return self._parse_search_results(data, search_type="keyword")

    def search_by_keyword_all_pages(self, keyword: str) -> List[Product1688]:
        """搜索多页结果并合并"""
        all_items = []
        for page in range(1, SEARCH_PAGES + 1):
            logger.info(f"  关键词搜索 [page={page}/{SEARCH_PAGES}]: {keyword[:40]}")
            items = self.search_by_keyword(keyword, page=page)
            all_items.extend(items)
            if len(items) < PAGE_SIZE:
                break  # 没有更多结果
            time.sleep(REQUEST_DELAY)
        return all_items

    # ================================================================
    # 图片搜索（拍立淘）
    # ================================================================

    def search_by_image(
        self,
        image_url: str,
        page: int = 1,
        page_size: int = PAGE_SIZE,
        sort: str = "sale_desc"
    ) -> List[Product1688]:
        """
        按图片搜索1688商品（拍立淘/以图搜款）

        Args:
            image_url: 图片URL（需为公网可访问URL）
            page: 页码
            page_size: 每页条数
            sort: 排序 - sale_desc(销量), price_asc(价格), default(默认)

        Returns:
            1688商品列表（包含相似度评分）
        """
        url = f"{ONEBOUND_BASE_URL}/item_search_img"
        params = {
            "key": self.api_key,
            "secret": self.api_secret,
            "imgid": image_url,
            "page": page,
            "page_size": page_size,
            "sort": sort,
        }

        data = self._request(url, params)
        # 图片搜索结果中可能带有 similarity 字段
        return self._parse_search_results(data, search_type="image")

    def search_by_image_all_pages(self, image_url: str) -> List[Product1688]:
        """图片搜索多页结果"""
        all_items = []
        for page in range(1, SEARCH_PAGES + 1):
            logger.info(f"  图片搜索 [page={page}/{SEARCH_PAGES}]")
            items = self.search_by_image(image_url, page=page)
            # 过滤低相似度
            items = [i for i in items if i.similarity >= IMAGE_SIMILARITY_THRESHOLD or i.search_type == "keyword"]
            all_items.extend(items)
            if len(items) < PAGE_SIZE:
                break
            time.sleep(REQUEST_DELAY)
        return all_items

    # ================================================================
    # 商品详情
    # ================================================================

    def get_item_detail(self, offer_id: str) -> Optional[Dict[str, Any]]:
        """获取商品详情（含SKU价格）"""
        url = f"{ONEBOUND_BASE_URL}/item_get"
        params = {
            "key": self.api_key,
            "secret": self.api_secret,
            "num_iid": offer_id,
        }
        data = self._request(url, params)
        if data and "item" in data:
            return data["item"]
        return None

    # ================================================================
    # 内部方法
    # ================================================================

    def _request(self, url: str, params: Dict) -> Optional[Dict]:
        """发送API请求，带重试和限流"""
        self._call_count += 1

        for attempt in range(MAX_RETRIES):
            try:
                # 限流：每次请求前等待
                if self._call_count > 1:
                    time.sleep(REQUEST_DELAY)

                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()

                data = resp.json()

                # 检查API层面的错误
                if isinstance(data, dict):
                    error_msg = data.get("error", "") or data.get("msg", "")
                    if error_msg and ("频率" in str(error_msg) or "limit" in str(error_msg).lower()):
                        wait = REQUEST_DELAY * (attempt + 1) * 2
                        logger.warning(f"触发频率限制，等待 {wait:.1f}s")
                        time.sleep(wait)
                        continue

                return data

            except requests.exceptions.Timeout:
                logger.warning(f"请求超时 (尝试 {attempt + 1}/{MAX_RETRIES})")
                time.sleep(REQUEST_DELAY * (attempt + 1))

            except requests.exceptions.RequestException as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(REQUEST_DELAY * (attempt + 1))

            except ValueError as e:
                logger.warning(f"JSON解析失败: {e}")
                time.sleep(REQUEST_DELAY)

        logger.error(f"请求彻底失败: {url}")
        return None

    def _parse_search_results(
        self,
        data: Optional[Dict],
        search_type: str = "keyword"
    ) -> List[Product1688]:
        """解析1688 API返回的搜索结果"""
        if not data:
            return []

        items = []

        # 尝试多种可能的返回格式
        item_list = []
        if isinstance(data, dict):
            # 格式1: {"items": {"item": [...]}}  (OneBound格式)
            if "items" in data and isinstance(data["items"], dict):
                item_list = data["items"].get("item", [])
            # 格式2: {"result": {"items": [...]}}
            elif "result" in data and isinstance(data["result"], dict):
                item_list = data["result"].get("items", [])
            # 格式3: {"data": {"items": [...]}}
            elif "data" in data and isinstance(data["data"], dict):
                item_list = data["data"].get("items", [])
            # 格式4: {"item": [...]} directly
            elif "item" in data:
                item_list = data["item"] if isinstance(data["item"], list) else [data["item"]]

        if not item_list:
            return []

        for raw in item_list:
            try:
                product = self._parse_single_item(raw, search_type)
                if product:
                    items.append(product)
            except Exception as e:
                logger.debug(f"解析单条商品失败: {e}")

        return items

    def _parse_single_item(self, raw: Dict, search_type: str) -> Optional[Product1688]:
        """解析单条商品数据"""
        # 提取价格
        price_str = str(raw.get("price", "0"))
        price_min, price_max = self._parse_price(price_str)

        # 跳过价格为0的结果
        if price_min <= 0 and price_max <= 0:
            return None

        # 提取相似度（图片搜索特有）
        similarity = 0.0
        if "similarity" in raw:
            try:
                similarity = float(raw["similarity"])
            except (ValueError, TypeError):
                pass
        elif "match_rate" in raw:
            try:
                similarity = float(raw["match_rate"])
            except (ValueError, TypeError):
                pass

        product = Product1688(
            offer_id=str(raw.get("num_iid", raw.get("offerId", ""))),
            title=str(raw.get("title", "")),
            price=price_str,
            price_min=price_min,
            price_max=price_max,
            min_order=str(raw.get("min_order", raw.get("minOrder", ""))),
            shop_name=str(raw.get("seller_nick", raw.get("shopName", raw.get("company", "")))),
            detail_url=str(raw.get("detail_url", raw.get("detailUrl", ""))),
            image_url=str(raw.get("pic_url", raw.get("picUrl", ""))),
            sales=self._parse_int(raw.get("sales", raw.get("sold", 0))),
            similarity=similarity,
            search_type=search_type,
            category=str(raw.get("cat_name", raw.get("category", ""))),
            location=str(raw.get("provcity", raw.get("location", raw.get("area", "")))),
            one_stop_service=str(raw.get("one_stop_service", "")).lower() in ("true", "1", "yes"),
        )
        return product

    @staticmethod
    def _parse_price(price_str: str) -> tuple:
        """解析价格字符串，返回 (最低价, 最高价)"""
        if not price_str:
            return 0.0, 0.0

        # 清除货币符号和单位
        cleaned = price_str.replace("¥", "").replace("元", "").replace(",", "").strip()

        # 处理价格范围 "15.00-20.00" 或 "15.00~20.00"
        for sep in ("-", "~", "—", " "):
            if sep in cleaned:
                parts = cleaned.split(sep)
                try:
                    p_min = float(parts[0].strip())
                    p_max = float(parts[-1].strip())
                    return min(p_min, p_max), max(p_min, p_max)
                except ValueError:
                    continue

        # 单一价格
        try:
            price = float(cleaned)
            return price, price
        except ValueError:
            return 0.0, 0.0

    @staticmethod
    def _parse_int(value: Any) -> int:
        """安全解析整数"""
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return 0
