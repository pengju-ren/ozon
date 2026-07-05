"""
途径 3: 1688 官方开放平台 API — 最合规、最稳定
📋 前提：营业执照 → open.1688.com 企业认证 → 创建应用 → 申请权限
📋 文档：https://open.1688.com
💰 API 免费，QPS 10~20次/秒

网关地址：
  搜索: https://gw.open.1688.com/openapi/param2/2/alibaba.offer.search/2.0
  详情: https://gw.open.1688.com/openapi/param2/2/alibaba.item.get/2.0
"""
import os
import time
import json
import hashlib
import urllib.parse
import logging
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

from .searcher_base import BaseSearcher, Product1688

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

# -- 配置 --
APP_KEY = os.getenv("ALIBABA_APP_KEY", "")
APP_SECRET = os.getenv("ALIBABA_APP_SECRET", "")
API_GATEWAY = "https://gw.open.1688.com/openapi/param2/2"
MAX_RETRIES = 3


class Alibaba1688Searcher(BaseSearcher):
    """
    1688 官方 API 搜索器

    接入步骤:
    1. open.1688.com → 企业认证 → 上传营业执照
    2. 创建自研应用 → 获取 AppKey / AppSecret
    3. 申请接口权限: alibaba.offer.search, alibaba.item.get
    4. 填入 .env: ALIBABA_APP_KEY=xxx, ALIBABA_APP_SECRET=xxx
    """

    def __init__(self, app_key: str = "", app_secret: str = ""):
        super().__init__(name="1688 官方 API")
        self.app_key = app_key or APP_KEY
        self.app_secret = app_secret or APP_SECRET

        if not self.app_key or not self.app_secret:
            logger.warning(
                "1688 官方 API 未配置。步骤:\n"
                "  1. open.1688.com → 企业认证\n"
                "  2. 创建应用 → 获取 AppKey/Secret\n"
                "  3. 申请接口: alibaba.offer.search\n"
                "  4. .env 中设置 ALIBABA_APP_KEY 和 ALIBABA_APP_SECRET"
            )

    # ----------------------------------------------------------
    # 以图搜款
    # ----------------------------------------------------------
    async def search_by_image(self, image_input: str) -> List[Product1688]:
        """
        1688 官方以图搜款 — 需要图片上传到阿里 OSS

        ⚠️ 1688 官方拍立淘接口需要图片先上传到阿里 OSS
        目前仅提供关键词搜索的完整实现
        如需图片搜索，请使用 OneBound API (途径1)
        """
        logger.info(
            "[1688官方API] 以图搜款需要图片上传阿里云OSS\n"
            "  建议: 使用 onebound 途径进行图片搜索"
        )
        return []

    # ----------------------------------------------------------
    # 关键词搜索 (核心功能)
    # ----------------------------------------------------------
    async def search_by_keyword(self, keyword: str) -> List[Product1688]:
        """
        关键词搜索 1688 商品

        接口: alibaba.offer.search (2.0版)
        """
        if not self.app_key:
            logger.warning("未配置 ALIBABA_APP_KEY")
            return []

        all_items = []

        for page in range(1, 3):
            biz = {
                "keywords": keyword,
                "pageNo": page,
                "pageSize": 30,
                "sortType": "booked",  # 成交量降序
            }

            data = self._call("alibaba.offer.search", biz)

            if data and data.get("offers"):
                items = self._parse_offers(data["offers"])
                all_items.extend(items)
                total = data.get("totalResult", 0)
                if page * 30 >= total:
                    break
            else:
                break

            time.sleep(0.3)

        logger.info(f"  [1688官方] '{keyword[:30]}': 找到 {len(all_items)} 个商品")
        return self._deduplicate(all_items)

    # ----------------------------------------------------------
    # 商品详情 (获取精确价格)
    # ----------------------------------------------------------
    def get_item_detail(self, offer_id: str | int) -> Optional[dict]:
        """
        获取商品详情 — 含完整阶梯批发价、SKU价格

        接口: alibaba.item.get
        """
        if not self.app_key:
            return None

        biz = {"offerId": int(offer_id)}
        return self._call("alibaba.item.get", biz)

    # ----------------------------------------------------------
    # API 签名与调用 (1688 2.0 标准)
    # ----------------------------------------------------------
    def _call(
        self,
        method: str,
        biz_params: dict,
        version: str = "2.0",
    ) -> Optional[dict]:
        """
        调用 1688 开放平台 API (2.0版网关)

        签名流程:
        1. 公共参数 (不含sign) + 业务参数 URL编码后放入 param2
        2. 所有参数按 key 字典序排序
        3. 拼接为 key+value 字符串
        4. sign = MD5(secret + 拼接串 + secret).upper()
        """
        # 1. 公共参数
        timestamp = str(int(time.time() * 1000))
        sys_params = {
            "method": method,
            "app_key": self.app_key,
            "timestamp": timestamp,
            "format": "json",
            "v": version,
            "sign_method": "md5",
        }

        # 2. 业务参数 → URL编码的 JSON 字符串 → 放入 param2
        biz_json = json.dumps(biz_params, ensure_ascii=False)
        api_params = {**sys_params, "param2": urllib.parse.quote(biz_json, safe="")}

        # 3. 签名
        api_params["sign"] = self._sign(api_params)

        # 4. 请求
        url = f"{API_GATEWAY}/{method.replace('.', '/')}/{version}"

        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.get(url, params=api_params, timeout=15)
                resp.raise_for_status()
                result = resp.json()

                # 检查 1688 错误
                if "error_code" in result:
                    self._handle_error(result, method)
                    return None

                # 提取实际数据
                if method.startswith("alibaba."):
                    result = result.get("result", result)

                return result

            except requests.exceptions.Timeout:
                logger.warning(f"  [1688官方] 超时 (尝试 {attempt+1})")
                time.sleep(1.5 * (attempt + 1))
            except requests.exceptions.RequestException as e:
                logger.warning(f"  [1688官方] 请求失败: {e}")
                time.sleep(1.5 * (attempt + 1))

        return None

    def _sign(self, params: dict) -> str:
        """
        1688 标准 MD5 签名

        sign = MD5( app_secret + sorted(k1v1k2v2...) + app_secret ).upper()
        """
        # 过滤 sign 字段和空值
        filtered = {
            k: v for k, v in params.items()
            if k != "sign" and v is not None
        }
        sorted_pairs = sorted(filtered.items(), key=lambda x: x[0])
        sign_str = "".join(f"{k}{v}" for k, v in sorted_pairs)
        raw = f"{self.app_secret}{sign_str}{self.app_secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    def _handle_error(self, result: dict, method: str):
        """解析 1688 API 错误"""
        code = result.get("error_code", "")
        msg = result.get("error_message", result.get("exception", ""))
        logger.warning(f"  [1688官方] API错误 {code}: {msg}")

        # 常见错误提示
        tips = {
            "403": "权限不足 — 请在 1688 开放平台申请接口权限",
            "40001": "签名错误 — 检查 AppSecret",
            "40002": "AppKey 无效",
            "40003": "应用未通过审核",
        }
        if code in tips:
            logger.warning(f"   💡 {tips[code]}")

    # ----------------------------------------------------------
    # 解析
    # ----------------------------------------------------------
    def _parse_offers(self, offers: list) -> List[Product1688]:
        """解析 alibaba.offer.search 返回的 offers 列表"""
        items = []

        for raw in offers:
            try:
                # 价格文本 (如 "15.00-28.00")
                price_text = str(raw.get("priceRange", raw.get("price", "0")))
                lo, hi = _parse_price(price_text)

                items.append(Product1688(
                    offer_id=str(raw.get("offerId", "")),
                    title=str(raw.get("subject", raw.get("title", ""))),
                    price_text=price_text,
                    price_low=lo,
                    price_high=hi,
                    min_order=str(raw.get("minOrderQuantity", raw.get("minOrder", ""))),
                    shop_name=str(raw.get("supplierName", raw.get("companyName", ""))),
                    location=str(raw.get("city", raw.get("location", ""))),
                    detail_url=(
                        f"https://detail.1688.com/offer/{raw.get('offerId', '')}.html"
                        if raw.get("offerId") else ""
                    ),
                    image_url=str(raw.get("imageUrl", "")),
                ))
            except Exception as e:
                logger.debug(f"  解析offer失败: {e}")

        return items

    @staticmethod
    def _deduplicate(items: List[Product1688]) -> List[Product1688]:
        seen = set()
        unique = []
        for item in items:
            key = item.offer_id or item.title
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique


def _parse_price(text: str) -> tuple:
    """ "15.00-28.00" → (15.00, 28.00) """
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
