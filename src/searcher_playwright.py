"""
途径 2: Playwright 模拟真人 — 浏览器自动化以图搜款
免费，无需营业执照，无需 API Key
模拟真人在1688点击以图搜货、上传图片、解析结果
"""
import re
import time
import random
import asyncio
import logging
from pathlib import Path
from typing import List

from .searcher_base import BaseSearcher, Product1688

logger = logging.getLogger(__name__)

IMAGE_DIR = Path(__file__).resolve().parent.parent / "output" / "images"


class PlaywrightSearcher(BaseSearcher):
    """Playwright 浏览器自动化搜索器 — 模拟真人操作1688"""

    def __init__(self, headless: bool = True):
        super().__init__(name="Playwright 模拟")
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._started = False

    async def _ensure_browser(self):
        """延迟启动浏览器"""
        if self._started:
            return

        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh']});
        """)
        self._page = await self._context.new_page()
        self._started = True
        logger.info("[Playwright] 浏览器已启动")

    # ----------------------------------------------------------
    # 以图搜款（核心）
    # ----------------------------------------------------------
    async def search_by_image(self, image_input: str) -> List[Product1688]:
        """
        以图搜款 — 支持本地文件路径或公网URL
        如果是URL，先下载到本地
        """
        if not image_input:
            return []

        # 确定本地路径
        local_path = Path(image_input)
        if image_input.startswith("http"):
            local_path = await self._download_image(image_input)

        if not local_path or not local_path.exists():
            logger.warning(f"[Playwright] 图片不存在: {image_input}")
            return []

        await self._ensure_browser()

        results = await self._try_image_search(local_path)
        if not results:
            results = await self._try_fallback_upload(local_path)

        results = self._deduplicate(results)
        logger.info(f"  [Playwright] 以图搜款: 找到 {len(results)} 个商品")
        return results

    async def _try_image_search(self, image_path: Path) -> List[Product1688]:
        """主方案：打开1688首页 → 点击相机 → 上传图片"""
        from playwright.async_api import TimeoutError as PWTimeout

        try:
            # 打开 1688
            await self._page.goto(
                "https://www.1688.com/",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            await self._sleep(1, 2)

            # 找图片搜索入口并点击
            clicked = False
            for sel in [
                '.alisearch-camera',
                '.search-img-btn',
                'img[alt*="拍照"]',
                'img[alt*="图片"]',
                '.image-search-entry',
                'i[class*="camera"]',
            ]:
                btn = await self._page.query_selector(sel)
                if btn:
                    await btn.click()
                    await self._sleep(0.5, 1.5)
                    clicked = True
                    break

            if not clicked:
                # 试试文字入口
                for link in await self._page.query_selector_all("a, span"):
                    try:
                        text = await link.inner_text()
                        if "以图搜" in text or "图片搜" in text or "拍照" in text:
                            await link.click()
                            await self._sleep(0.5, 1.5)
                            clicked = True
                            break
                    except Exception:
                        continue

            if not clicked:
                # 直接用搜索页
                await self._page.goto(
                    "https://s.1688.com/selloffer/offer_search.htm?imageSearch=1",
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                await self._sleep(1, 2)

            # 上传图片
            file_input = await self._page.query_selector('input[type="file"]')
            if not file_input:
                logger.debug("  [Playwright] 未找到上传按钮")
                return []

            await file_input.set_input_files(str(image_path))
            await self._sleep(3, 5)  # 等上传+识别

            # 解析结果
            return await self._extract_results()

        except PWTimeout:
            logger.debug("  [Playwright] 主方案超时")
            return []
        except Exception as e:
            logger.debug(f"  [Playwright] 主方案出错: {e}")
            return []

    async def _try_fallback_upload(self, image_path: Path) -> List[Product1688]:
        """备用方案：直接用搜索页URL"""
        try:
            await self._page.goto(
                "https://s.1688.com/selloffer/offer_search.htm",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            await self._sleep(1, 2)

            # 找页面上的相机/图片搜索入口
            img_upload_btn = await self._page.query_selector(
                '[class*="image"], [class*="camera"]'
            )
            if img_upload_btn:
                await img_upload_btn.click()
                await self._sleep(1, 2)

            file_input = await self._page.query_selector('input[type="file"]')
            if file_input:
                await file_input.set_input_files(str(image_path))
                await self._sleep(3, 5)
                return await self._extract_results()

        except Exception as e:
            logger.debug(f"  [Playwright] 备用方案出错: {e}")

        return []

    # ----------------------------------------------------------
    # 关键词搜索
    # ----------------------------------------------------------
    async def search_by_keyword(self, keyword: str) -> List[Product1688]:
        """关键词搜索"""
        if not keyword:
            return []

        await self._ensure_browser()

        from urllib.parse import quote

        try:
            search_url = (
                f"https://s.1688.com/selloffer/offer_search.htm?"
                f"keywords={quote(keyword)}&n=y"
            )
            await self._page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=20000,
            )
            await self._sleep(1.5, 3)

            results = await self._extract_results()
            results = self._deduplicate(results)
            logger.info(f"  [Playwright] 关键词搜索: 找到 {len(results)} 个商品")
            return results

        except Exception as e:
            logger.warning(f"  [Playwright] 关键词搜索出错: {e}")
            return []

    # ----------------------------------------------------------
    # 结果解析
    # ----------------------------------------------------------
    async def _extract_results(self) -> List[Product1688]:
        """从当前页面提取商品列表"""
        products = []

        html = await self._page.content()

        # 策略1: data 属性
        offer_ids = re.findall(r'data-offerid="(\d+)"', html)
        titles = re.findall(r'data-offer-title="([^"]*)"', html)
        prices = re.findall(r'data-offer-price="([^"]*)"', html)

        if offer_ids:
            for i in range(min(len(offer_ids), 20)):
                price_text = prices[i] if i < len(prices) else ""
                lo, hi = _parse_price(price_text)
                products.append(Product1688(
                    offer_id=offer_ids[i],
                    title=titles[i] if i < len(titles) else "",
                    price_text=price_text,
                    price_low=lo,
                    price_high=hi,
                    detail_url=f"https://detail.1688.com/offer/{offer_ids[i]}.html",
                ))

        # 策略2: 从CSS卡片提取
        if not products:
            for sel in [
                '.space-offer-card', '.sm-offer-item', '.offer-list-item',
                'li[class*="offer"]', 'div[class*="offer-item"]',
            ]:
                cards = await self._page.query_selector_all(sel)
                if cards:
                    for card in cards[:20]:
                        p = await self._parse_card(card)
                        if p and p.price_low > 0:
                            products.append(p)
                    break

        # 去重
        seen = set()
        unique = []
        for p in products:
            key = p.offer_id or p.title[:30]
            if key and key not in seen:
                seen.add(key)
                unique.append(p)

        return unique

    async def _parse_card(self, card) -> "Product1688 | None":
        """解析单个商品卡片"""
        try:
            # 标题
            title_el = await card.query_selector(
                'a[class*="title"], h3 a, .title, [class*="subject"]'
            )
            title = (await title_el.inner_text()).strip() if title_el else ""

            # 价格
            price_el = await card.query_selector(
                '[class*="price"], .price-num'
            )
            price_text = (await price_el.inner_text()).strip() if price_el else ""

            # 链接
            link_el = await card.query_selector('a[href*="offer"]')
            href = await link_el.get_attribute("href") if link_el else ""
            if href:
                href = f"https:{href}" if href.startswith("//") else href

            lo, hi = _parse_price(price_text)
            return Product1688(
                title=title,
                price_text=price_text,
                price_low=lo,
                price_high=hi,
                detail_url=href,
            )
        except Exception:
            return None

    # ----------------------------------------------------------
    # 辅助
    # ----------------------------------------------------------
    async def _download_image(self, url: str) -> "Path | None":
        """下载图片到本地"""
        import requests
        import hashlib

        name_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        local_path = IMAGE_DIR / f"{name_hash}.jpg"
        if local_path.exists() and local_path.stat().st_size > 100:
            return local_path

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
                "Referer": "https://www.ozon.ru/",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
        except Exception:
            return None

    @staticmethod
    async def _sleep(min_s: float, max_s: float):
        await asyncio.sleep(random.uniform(min_s, max_s))

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

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


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
