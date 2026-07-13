"""
途径 5: search1688api — 1688 H5 内部 API 搜索器
调用 h5api.m.1688.com 的移动端接口，免费、无需营业执照、无需浏览器

原理: 逆向1688手机端H5接口，base64上传图片 → 拿imageId → 调推荐接口 → 解析JSONP
pip install search1688api  (或 pip install -e search1688api_src/)
"""
import hashlib
import logging
from pathlib import Path
from typing import List, Optional

import requests

from .searcher_base import BaseSearcher, Product1688

logger = logging.getLogger(__name__)

IMAGE_DIR = Path(__file__).resolve().parent.parent / "output" / "images"


class Search1688ApiSearcher(BaseSearcher):
    """search1688api H5 API 搜索器 — 调用 1688 移动端内部接口"""

    def __init__(self, debug: bool = False):
        super().__init__(name="search1688api H5")
        self.debug = debug
        self._session = None

    # ----------------------------------------------------------
    # Async context manager（桥接 Sync1688Session 生命周期）
    # ----------------------------------------------------------
    async def __aenter__(self):
        from search1688api import Sync1688Session

        self._session = Sync1688Session(debug=self.debug)
        self._session.__enter__()  # 触发 start() → cookie/token 初始化
        logger.info("[search1688api] Session 初始化完成")
        return self

    async def __aexit__(self, *args):
        if self._session:
            self._session.__exit__(*args)
            self._session = None
            logger.info("[search1688api] Session 已关闭")

    # ----------------------------------------------------------
    # 以图搜款
    # ----------------------------------------------------------
    # 1688 H5 图片上传限制（超过会报 "store image error"）
    _IMAGE_MAX_PX = 200

    async def search_by_image(self, image_input: str) -> List[Product1688]:
        """
        以图搜款 — 支持本地文件路径或公网URL
        如果是URL，先下载到本地缓存
        """
        if not image_input:
            return []

        # 如果是 URL，先下载
        local_path = Path(image_input)
        if image_input.startswith("http"):
            downloaded = await self._download_image(image_input)
            if downloaded:
                local_path = downloaded
            else:
                return []

        if not local_path.exists():
            logger.warning(f"[search1688api] 图片不存在: {image_input}")
            return []

        # 1688 H5 API 对上传图片大小有限制，需要先缩放
        search_path = await self._resize_for_search(local_path)

        try:
            raw_items = self._session.search_by_image(str(search_path))
        except Exception as e:
            logger.warning(f"[search1688api] 以图搜款异常: {e}")
            return []

        products = self._convert_to_products(raw_items)
        products = self._deduplicate(products)
        logger.info(f"  [search1688api] 以图搜款: 找到 {len(products)} 个商品")
        return products

    # ----------------------------------------------------------
    # 关键词搜索
    # ----------------------------------------------------------
    async def search_by_keyword(self, keyword: str) -> List[Product1688]:
        """关键词搜索"""
        if not keyword:
            return []

        try:
            raw_items = self._session.search_by_text(keyword)
        except Exception as e:
            logger.warning(f"[search1688api] 关键词搜索异常: {e}")
            return []

        products = self._convert_to_products(raw_items)
        products = self._deduplicate(products)
        logger.info(
            f"  [search1688api] 关键词搜索 '{keyword[:30]}': 找到 {len(products)} 个商品"
        )
        return products

    # ----------------------------------------------------------
    # 数据转换：search1688api 原始 dict → Product1688
    # ----------------------------------------------------------
    def _convert_to_products(self, raw_items: list) -> List[Product1688]:
        """
        将 search1688api 返回的原始 dict 列表转换为 Product1688

        原始数据格式（search1688api 透传 1688 H5 API）：
        {
            "data": {
                "offerId": "...",
                "title": "...",
                "priceInfo": {"price": "15.00-28.00"},
                "shopAddition": {"text": "店铺名"},
                "province": "广东", "city": "广州",
                "saleQuantity": 1234,
                "bookedCount": 567,
                "beginAmount": 2,
                "imageUrl": "...",
                "tags": [{"text": "一件代发"}, ...],
            }
        }
        """
        products = []
        for item in raw_items:
            try:
                d = item.get("data", {})
                if not d:
                    continue

                offer_id = str(d.get("offerId", ""))
                if not offer_id:
                    continue

                title = str(d.get("title", ""))

                # 价格解析
                price_info = d.get("priceInfo", {})
                price_text = str(price_info.get("price", "")) if price_info else ""
                price_lo, price_hi = _parse_price(price_text)

                # 店铺
                shop_info = d.get("shopAddition", {})
                shop_name = str(shop_info.get("text", "")) if shop_info else ""

                # 所在地
                province = str(d.get("province", ""))
                city = str(d.get("city", ""))
                location = f"{province} {city}".strip()

                # 销量
                sales = _parse_int(
                    d.get("saleQuantity", d.get("bookedCount", 0))
                )

                # 起批量
                min_order = str(d.get("beginAmount", d.get("minOrder", "")))

                # 主图（字段名可能变化，多试几个）
                image_url = str(
                    d.get("imageUrl", d.get("image", d.get("picUrl", "")))
                )

                # 一件代发检测（通过 tags）
                one_stop = False
                tags = d.get("tags", [])
                if isinstance(tags, list):
                    for tag in tags:
                        text = (
                            tag.get("text", "") if isinstance(tag, dict) else str(tag)
                        )
                        if any(kw in text for kw in ("一件代发", "代发", "一件")):
                            one_stop = True
                            break

                product = Product1688(
                    offer_id=offer_id,
                    title=title,
                    price_text=price_text,
                    price_low=price_lo,
                    price_high=price_hi,
                    min_order=min_order,
                    shop_name=shop_name,
                    location=location,
                    detail_url=(
                        f"https://detail.1688.com/offer/{offer_id}.html"
                        if offer_id else ""
                    ),
                    image_url=image_url,
                    sales=sales,
                    similarity=0.0,       # H5 API 不返回相似度
                    one_stop=one_stop,
                )

                if product.price_low > 0:
                    products.append(product)

            except Exception as e:
                logger.debug(f"  [search1688api] 商品解析失败: {e}")
                continue

        return products

    # ----------------------------------------------------------
    # 图片预处理（1688 H5 API 对上传图片有大小限制）
    # ----------------------------------------------------------
    async def _resize_for_search(self, image_path: Path) -> Path:
        """
        将图片缩放到 1688 H5 API 可接受的大小（最长边 ≤ 200px）
        返回缩放后的临时图片路径
        """
        # 如果已存在缩放版本，直接复用
        resized_path = image_path.parent / f"{image_path.stem}_s{image_path.suffix}"
        if resized_path.exists() and resized_path.stat().st_size > 100:
            return resized_path

        try:
            from PIL import Image

            img = Image.open(image_path)
            w, h = img.size
            max_dim = max(w, h)

            if max_dim <= self._IMAGE_MAX_PX:
                # 已经足够小，直接返回原图
                return image_path

            # 等比缩放
            ratio = self._IMAGE_MAX_PX / max_dim
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)

            # 保存缩放版本
            img.save(resized_path, quality=85)
            logger.debug(
                f"  [search1688api] 图片缩放: {w}x{h} → {new_size[0]}x{new_size[1]}"
            )
            return resized_path

        except Exception as e:
            logger.debug(f"  [search1688api] 图片缩放失败，用原图: {e}")
            return image_path

    # ----------------------------------------------------------
    # 图片下载（URL → 本地缓存）
    # ----------------------------------------------------------
    async def _download_image(self, url: str) -> Optional[Path]:
        """下载图片到本地缓存，返回本地路径"""
        name_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        local_path = IMAGE_DIR / f"{name_hash}.jpg"

        # 已缓存且有效
        if local_path.exists() and local_path.stat().st_size > 100:
            return local_path

        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.ozon.ru/",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
        except Exception as e:
            logger.warning(f"  [search1688api] 图片下载失败: {e}")
            return None

    # ----------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------
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


# ============================================================
# 模块级工具函数（兼容各 searcher 共用的 _parse_price 模式）
# ============================================================
def _parse_price(text: str) -> tuple:
    """ "¥15.50-28.00" → (15.50, 28.00) """
    if not text:
        return 0.0, 0.0
    text = str(text).replace("¥", "").replace("￥", "").replace(",", "").strip()
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


def _parse_int(val) -> int:
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return 0
