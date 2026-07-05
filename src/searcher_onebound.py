"""
途径 1: OneBound API — 第三方1688数据接口
无需营业执照，每日500次免费，付费~100元/万次
注册: https://open-claw.cn
"""
import os
import time
import logging
import hashlib
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

from .searcher_base import BaseSearcher, Product1688

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

# -- 配置 --
API_KEY = os.getenv("ONEBOUND_API_KEY", "")
API_SECRET = os.getenv("ONEBOUND_API_SECRET", "")
BASE_URL = "https://api-gw.onebound.cn/1688"
REQUEST_DELAY = 1.0
MAX_RETRIES = 3
TIMEOUT = 30


class OneBoundSearcher(BaseSearcher):
    """OneBound API 搜索器"""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        super().__init__(name="OneBound API")
        self.api_key = api_key or API_KEY
        self.api_secret = api_secret or API_SECRET
        self._call_count = 0

        if not self.api_key or not self.api_secret:
            logger.warning("OneBound API Key/Secret 未配置，搜索将返回空结果")

    # ----------------------------------------------------------
    # 以图搜款
    # ----------------------------------------------------------
    async def search_by_image(self, image_input: str) -> List[Product1688]:
        """
        以图搜款：支持公网图片 URL
        """
        if not image_input:
            return []

        # OneBound 图片搜索需要公网 URL
        # 如果传的是本地路径，我们无法直接用
        if not image_input.startswith("http"):
            logger.warning("OneBound 以图搜款需要公网URL，请使用 Ozon 原始图片链接")
            # 尝试用 Ozon 原始 URL
            return []

        all_items = []
        for page in range(1, 3):  # 搜2页
            items = self._search_by_image_page(image_input, page)
            all_items.extend(items)
            if len(items) < 20:
                break
            time.sleep(REQUEST_DELAY)

        logger.info(f"  [OneBound] 以图搜款: 找到 {len(all_items)} 个商品")
        return self._deduplicate(all_items)

    def _search_by_image_page(self, image_url: str, page: int) -> List[Product1688]:
        """图片搜索单页"""
        params = {
            "key": self.api_key,
            "secret": self.api_secret,
            "imgid": image_url,
            "page": page,
            "page_size": 30,
            "sort": "sale_desc",
        }
        data = self._call(f"{BASE_URL}/item_search_img", params)
        return self._parse_items(data, "image")

    # ----------------------------------------------------------
    # 关键词搜索
    # ----------------------------------------------------------
    async def search_by_keyword(self, keyword: str) -> List[Product1688]:
        """关键词搜索"""
        if not keyword:
            return []

        all_items = []
        for page in range(1, 3):
            items = self._search_by_keyword_page(keyword, page)
            all_items.extend(items)
            if len(items) < 20:
                break
            time.sleep(REQUEST_DELAY)

        logger.info(f"  [OneBound] 关键词搜索 '{keyword[:30]}': 找到 {len(all_items)} 个商品")
        return self._deduplicate(all_items)

    def _search_by_keyword_page(self, keyword: str, page: int) -> List[Product1688]:
        """关键词搜索单页"""
        params = {
            "key": self.api_key,
            "secret": self.api_secret,
            "q": keyword,
            "page": page,
            "page_size": 30,
            "sort": "default",
        }
        data = self._call(f"{BASE_URL}/item_search", params)
        return self._parse_items(data, "keyword")

    # ----------------------------------------------------------
    # API 调用
    # ----------------------------------------------------------
    def _call(self, url: str, params: dict) -> Optional[dict]:
        """发送API请求，带重试"""
        self._call_count += 1
        if self._call_count > 1:
            time.sleep(REQUEST_DELAY)

        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT)
                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    logger.warning(f"  [OneBound] API错误: {data.get('error', '')[:100]}")
                    return None

                return data

            except requests.exceptions.Timeout:
                logger.warning(f"  [OneBound] 超时 (尝试 {attempt+1}/{MAX_RETRIES})")
                time.sleep(REQUEST_DELAY * (attempt + 1))
            except requests.exceptions.RequestException as e:
                logger.warning(f"  [OneBound] 请求失败: {e}")
                time.sleep(REQUEST_DELAY * (attempt + 1))
            except ValueError:
                return None

        return None

    # ----------------------------------------------------------
    # 解析
    # ----------------------------------------------------------
    def _parse_items(self, data: Optional[dict], search_type: str) -> List[Product1688]:
        """解析 OneBound API 返回的商品列表"""
        if not data:
            return []

        items = []

        # 提取 item 列表
        item_list = []
        if isinstance(data, dict):
            if "items" in data and isinstance(data["items"], dict):
                item_list = data["items"].get("item", [])
            elif "item" in data:
                item_list = data["item"] if isinstance(data["item"], list) else [data["item"]]

        for raw in item_list:
            try:
                price_text = str(raw.get("price", "0"))
                price_lo, price_hi = self._parse_price(price_text)

                # 相似度（图片搜索有）
                sim = 0.0
                for key in ("similarity", "match_rate"):
                    if key in raw:
                        try:
                            sim = float(raw[key])
                        except (ValueError, TypeError):
                            pass

                product = Product1688(
                    offer_id=str(raw.get("num_iid", "")),
                    title=str(raw.get("title", "")),
                    price_text=price_text,
                    price_low=price_lo,
                    price_high=price_hi,
                    min_order=str(raw.get("min_order", "")),
                    shop_name=str(raw.get("seller_nick", raw.get("company", ""))),
                    location=str(raw.get("provcity", raw.get("area", ""))),
                    detail_url=str(raw.get("detail_url", "")),
                    image_url=str(raw.get("pic_url", "")),
                    sales=self._parse_int(raw.get("sales", 0)),
                    similarity=sim,
                    one_stop=str(raw.get("one_stop_service", "")).lower() in ("true", "1"),
                )

                if product.price_low > 0:
                    items.append(product)

            except Exception as e:
                logger.debug(f"  解析失败: {e}")

        return items

    @staticmethod
    def _parse_price(text: str) -> tuple:
        if not text:
            return 0.0, 0.0
        text = str(text).replace("¥", "").replace("元", "").replace(",", "").strip()
        for sep in ("-", "~", "—"):
            if sep in text:
                parts = text.split(sep)
                try:
                    lo, hi = float(parts[0].strip()), float(parts[-1].strip())
                    return min(lo, hi), max(lo, hi)
                except ValueError:
                    continue
        try:
            p = float(text)
            return p, p
        except ValueError:
            return 0.0, 0.0

    @staticmethod
    def _parse_int(val) -> int:
        try:
            return int(float(str(val)))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _deduplicate(items: List[Product1688]) -> List[Product1688]:
        seen = set()
        unique = []
        for item in items:
            key = item.offer_id or item.title[:30]
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    async def close(self):
        pass
