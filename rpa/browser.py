"""
RPA 浏览器引擎 — 基于 Playwright 实现网页自动化操作
影刀式的点选/输入/下载/等待能力
"""

import asyncio
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, Download

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = ROOT / "output" / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


class RPABrowser:
    """
    RPA 浏览器 — 影刀式自动操作

    用法:
        browser = RPABrowser(headless=False)
        await browser.start()
        await browser.goto("https://example.com")
        await browser.click("button#login")
        await browser.fill("input[name='username']", "admin")
        await browser.download_click("a.download-link")
        await browser.close()
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._pending_downloads = []

    # ============================================================
    # 启动 / 关闭
    # ============================================================
    async def start(self):
        """启动浏览器，配置下载路径"""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
        )
        context = await self._browser.new_context(
            accept_downloads=True,
        )
        self._page = await context.new_page()
        # 监听下载事件
        self._pending_downloads = []
        self._page.on("download", lambda dl: self._pending_downloads.append(dl))
        print(f"🌐 浏览器已启动 (headless={self.headless})")
        return self

    async def close(self):
        """关闭浏览器"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        print("🌐 浏览器已关闭")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    # ============================================================
    # 基础动作 — 影刀式的点选操作
    # ============================================================
    async def goto(self, url: str, wait_until: str = "domcontentloaded"):
        """导航到指定URL"""
        print(f"📍 导航: {url}")
        await self.page.goto(url, wait_until=wait_until)

    async def click(self, selector: str, timeout: int = 10000):
        """
        点击元素 — 支持多个备选选择器（用 || 分隔）
        如果匹配到多个元素，自动点击第一个可见的
        例如: click("button:has-text('登录') || input[value='登录']")
        """
        for sel in (s.strip() for s in selector.split("||")):
            try:
                loc = self.page.locator(sel)
                # 如果匹配到多个，只点可见的
                count = await loc.count()
                if count > 1:
                    visible = loc.locator("visible=true")
                    vc = await visible.count()
                    if vc > 0:
                        await visible.first.click(timeout=timeout)
                        print(f"🖱️  点击: {sel} (从{count}个中选可见的)")
                        return
                await loc.first.click(timeout=2000)
                print(f"🖱️  点击: {sel}")
                return
            except Exception:
                continue
        # 全部失败，用第一个重试
        first = selector.split("||")[0].strip()
        print(f"🖱️  点击(重试): {first}")
        await self.page.locator(first).first.click(timeout=timeout)

    async def fill(self, selector: str, text: str, timeout: int = 10000):
        """
        输入文本 — 支持多个备选选择器（用 || 分隔），依次尝试直到成功
        例如: fill("input[name='user'] || input[type='text']", "admin")
        """
        for sel in (s.strip() for s in selector.split("||")):
            try:
                await self.page.wait_for_selector(sel, timeout=2000)
                await self.page.fill(sel, text)
                print(f"⌨️  输入: {sel} ← '{text}'")
                return
            except Exception:
                continue
        # 全部失败，用第一个重试
        first = selector.split("||")[0].strip()
        print(f"⌨️  输入(重试): {first} ← '{text}'")
        await self.page.wait_for_selector(first, timeout=timeout)
        await self.page.fill(first, text)

    async def select(self, selector: str, value: str, timeout: int = 10000):
        """下拉框选择"""
        print(f"📋 选择: {selector} ← '{value}'")
        await self.page.wait_for_selector(selector, timeout=timeout)
        await self.page.select_option(selector, value)

    async def hover(self, selector: str, timeout: int = 10000):
        """鼠标悬停 — 支持 || 多选择器"""
        for sel in (s.strip() for s in selector.split("||")):
            try:
                await self.page.locator(sel).first.hover(timeout=2000)
                print(f"👆 悬停: {sel}")
                return
            except Exception:
                continue
        first = selector.split("||")[0].strip()
        print(f"👆 悬停(重试): {first}")
        await self.page.locator(first).first.hover(timeout=timeout)

    async def press(self, key: str):
        """键盘按键"""
        print(f"⌨️  按键: {key}")
        await self.page.keyboard.press(key)

    async def scroll_to(self, selector: str, timeout: int = 10000):
        """滚动到元素 — 支持 || 多选择器"""
        sel = selector.split("||")[0].strip()
        await self.page.locator(sel).first.wait_for(timeout=timeout)
        await self.page.locator(sel).first.scroll_into_view_if_needed()

    # ============================================================
    # 等待 & 判断
    # ============================================================
    async def wait_for(self, selector: str, timeout: int = 30000):
        """等待元素出现 — 支持 || 多选择器"""
        for sel in (s.strip() for s in selector.split("||")):
            try:
                await self.page.locator(sel).first.wait_for(timeout=timeout)
                print(f"⏳ 等待: {sel}")
                return
            except Exception:
                continue
        first = selector.split("||")[0].strip()
        print(f"⏳ 等待(重试): {first}")
        await self.page.locator(first).first.wait_for(timeout=timeout)

    async def wait_for_text(self, text: str, timeout: int = 30000):
        """等待页面中出现指定文本"""
        print(f"⏳ 等待文本: {text}")
        await self.page.wait_for_selector(f"text={text}", timeout=timeout)

    async def is_visible(self, selector: str, timeout: int = 3000) -> bool:
        """判断元素是否可见"""
        try:
            await self.page.wait_for_selector(selector, timeout=timeout, state="visible")
            return True
        except Exception:
            return False

    async def get_text(self, selector: str) -> str:
        """获取元素文本"""
        return await self.page.inner_text(selector)

    # ============================================================
    # 下载
    # ============================================================
    async def download_click(self, selector: str, save_name: str = "",
                              timeout: int = 30000) -> Optional[Path]:
        """
        点击下载按钮 → 等待下载完成 → 保存到本地
        返回保存的文件路径，失败返回 None
        """
        print(f"📥 下载点击: {selector}")
        dl_start = len(self._pending_downloads)

        # 用 self.click（支持 || 多选择器）
        for sel in (s.strip() for s in selector.split("||")):
            try:
                await self.page.locator(sel).first.click(timeout=2000)
                break
            except Exception:
                continue
        else:
            first = selector.split("||")[0].strip()
            await self.page.locator(first).first.click(timeout=timeout)

        # 等新下载出现
        try:
            await asyncio.wait_for(self._wait_new_download(dl_start), timeout=timeout / 1000)
        except asyncio.TimeoutError:
            print("  ⚠️ 下载超时（可能是浏览器默认下载，检查 ~/Downloads）")
            return None

        download = self._pending_downloads[-1]
        filename = save_name or download.suggested_filename
        save_path = DOWNLOAD_DIR / filename
        await download.save_as(str(save_path))
        print(f"📁 已保存: {save_path}")
        return save_path

    async def _wait_new_download(self, prev_count: int):
        """等待新下载出现"""
        while len(self._pending_downloads) <= prev_count:
            await asyncio.sleep(0.2)

    # ============================================================
    # 截图
    # ============================================================
    async def screenshot(self, name: str = "screenshot"):
        """全页截图"""
        path = DOWNLOAD_DIR / f"{name}.png"
        await self.page.screenshot(path=str(path), full_page=True)
        print(f"📸 截图: {path}")
        return path

    # ============================================================
    # JavaScript 执行
    # ============================================================
    async def execute(self, js: str):
        """执行 JavaScript"""
        return await self.page.evaluate(js)
