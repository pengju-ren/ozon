"""
Seerfar 全自动 RPA — 完整流程

登录 → 热销榜单选品 → 进阶 → RFBS/近30天 → 查询
→ 毛利率降序 → 导出CSV
"""

import sys
import asyncio
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from browser import RPABrowser

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / "output" / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def main():
    browser = RPABrowser(headless=False)
    await browser.start()
    page = browser.page

    # ================================================================
    # Step 1-2: 打开 + 登录（带 502 重试）
    # ================================================================
    print("\n📍 打开 Seerfar...")
    for attempt in range(3):
        try:
            await browser.goto("https://www.seerfar.com/admin/index.html")
            await asyncio.sleep(4)
            # 检查是否 502
            body = await page.inner_text("body")
            if "502" in body and "Bad Gateway" in body:
                print(f"  ⚠️ 502 Bad Gateway，第{attempt+1}次重试...")
                await asyncio.sleep(5)
                continue
            break
        except Exception as e:
            print(f"  ⚠️ 加载失败: {e}，第{attempt+1}次重试...")
            await asyncio.sleep(5)

    print("🔐 登录...")
    await browser.fill(
        "input[placeholder*='账号'] || input[placeholder*='用户名'] || "
        "input[type='email'] || input[type='text']",
        "yzl666"
    )
    await asyncio.sleep(0.5)
    await browser.fill(
        "input[placeholder*='密码'] || input[type='password'] || "
        "input[name*='password'] || input[placeholder*='Password']",
        "yzl666888"
    )
    await browser.click("button:has-text('登 录') || button:has-text('登录') || button:has-text('登陆')")
    await asyncio.sleep(4)
    print(f"✅ 登录完成 — {page.url}")

    # ================================================================
    # Step 3: 功能 → 热销榜单选品
    #     hover "功能" 展开菜单，等 hot-mark 可见后点击
    # ================================================================
    print("\n📂 悬停'功能' → 点击'热销榜单选品'...")
    await browser.hover("a.capability || a.dropdown-toggle", timeout=5000)
    await asyncio.sleep(2)
    # 等 hot-mark 可见再点
    try:
        await page.locator("div.hot-mark").wait_for(state="visible", timeout=5000)
    except Exception:
        pass
    await page.locator("div.hot-mark").first.click(force=True, timeout=5000)
    await asyncio.sleep(4)
    print(f"✅ 已进入热销榜单选品 — {page.url}")

    # ================================================================
    # Step 4: 点击右上角"进阶"按钮
    # ================================================================
    print("\n🔧 点击'进阶'...")
    # 先截图看页面结构
    await browser.screenshot("s1_before_advance")

    # 找进阶按钮 — 可能在按钮栏、右上角
    # 用多选择器兜底
    try:
        await browser.click("button:has-text('进阶') || text=进阶 >> visible=true", timeout=5000)
    except Exception:
        # 如果没找到按钮形式的，尝试其他
        await browser.click("text=进阶", timeout=5000)
    await asyncio.sleep(2)
    await browser.screenshot("s2_advanced_open")
    print(f"✅ 进阶面板已展开")

    # ================================================================
    # Step 5: 设置筛选条件
    #
    # 关键发现: 配送方式/上架时间用的是 TomSelect 组件（原生 select 被隐藏）
    # 必须通过 TomSelect API 设值，或者点击 TomSelect 的可见 UI
    # ================================================================
    print("\n⚙️  设置筛选条件...")

    # 5a. 配送方式 → 原生 <select id="fulfillment">
    #     选项: OZON / FBS / FBO / RFBS / FBP
    try:
        await page.select_option("#fulfillment", "RFBS")
        print("  ✅ 配送方式 → RFBS (原生 select)")
    except Exception as e:
        print(f"  ⚠️ 配送方式失败: {e}")

    await asyncio.sleep(0.5)

    # 5b. 上架时间 → select_option 改值 + TomSelect API 同步 UI
    #     #creationDate option value: 1=近30天, 3=近90天, 6=近180天...
    try:
        await page.select_option("#creationDate", "近30天")
        await page.evaluate("document.querySelector('#creationDate').tomselect.setValue('1')")
        print("  ✅ 上架时间 → 近30天")
    except Exception as e:
        print(f"  ⚠️ 上架时间失败: {e}")

    await asyncio.sleep(0.5)
    await browser.screenshot("s3_filters_set")
    print("✅ 筛选条件已设置")

    # ================================================================
    # Step 6: 点击"查询"
    # ================================================================
    print("\n🔍 点击查询...")
    await browser.click("button:has-text('查询') || button:has-text('查 询') || input[value*='查询']", timeout=5000)
    print("  等待数据加载...")
    await asyncio.sleep(6)

    # 等表格出现（毛利率 或 表格行）
    try:
        await browser.wait_for("text=毛利率 >> visible=true", timeout=15000)
        print("  ✅ 表格已加载")
    except Exception:
        print("  ⚠️ 表格加载较慢，继续...")
        await asyncio.sleep(4)

    await browser.screenshot("s4_query_result")

    # ================================================================
    # Step 7: 毛利率降序排列
    #     这个表是 Bootstrap Table，点一次 th-inner 直接降序
    #     如果首点变成了 asc，再点一次切 desc
    # ================================================================
    print("\n📊 设置毛利率降序...")
    await page.locator("th[data-field='grossMargin'] .th-inner").first.click()
    await asyncio.sleep(1.5)

    is_desc = await page.evaluate("""
        (() => {
            const th = document.querySelector('th[data-field="grossMargin"]');
            if (!th) return false;
            return th.getAttribute('aria-sort') === 'descending' ||
                   th.classList.contains('desc');
        })()
    """)
    if not is_desc:
        print("  当前非降序，再点一次...")
        await page.locator("th[data-field='grossMargin'] .th-inner").first.click()
        await asyncio.sleep(1)

    print("✅ 毛利率降序排列完毕")
    await browser.screenshot("s5_margin_desc")

    # 排序触发表格重新加载，等 loading 消失
    try:
        # 等 loading 出现再消失（Bootstrap Table 的加载遮罩）
        await page.wait_for_selector(".fixed-table-loading", state="visible", timeout=3000)
        print("  ⏳ 表格排序加载中...")
    except Exception:
        pass
    try:
        await page.wait_for_selector(".fixed-table-loading", state="hidden", timeout=15000)
        print("  ✅ 排序加载完成")
    except Exception:
        pass
    await asyncio.sleep(2)  # 再稳一下

    # ================================================================
    # Step 8: 导出 CSV
    #     1. 点"导出"→ 2. 下拉选"CSV"→ 3. 弹窗点"导出"→ 等下载
    # ================================================================
    print("\n📥 导出CSV...")

    # 8a. 点导出按钮，出现下拉菜单
    await browser.click("button:has-text('导出') || text=导出 >> visible=true", timeout=5000)
    await asyncio.sleep(1.5)
    await browser.screenshot("s6_export_dropdown")

    # 8b. 在下拉菜单里选 CSV
    try:
        await page.locator("text=CSV").last.click(timeout=5000)
        print("  ✅ 已选CSV格式")
        await asyncio.sleep(1)
    except Exception as e:
        print(f"  ⚠️ CSV选择失败: {e}，尝试继续...")

    await browser.screenshot("s7_export_dialog")

    # 8c. 弹窗里改条数：默认200 → 2000
    try:
        count_input = page.locator(".export-input .el-input__inner").first
        await count_input.click()
        await asyncio.sleep(0.3)
        await count_input.fill("")  # 清空
        await count_input.fill("2000")
        print("  ✅ 导出条数: 2000")
    except Exception as e:
        print(f"  ⚠️ 修改条数失败: {e}")

    await browser.screenshot("s8_export_count_set")

    # 8d. 弹窗里点确认导出按钮
    saved = await browser.download_click(
        "button:has-text('导出') || button:has-text('确 定') || button:has-text('确定')",
        timeout=30000,
    )
    await asyncio.sleep(4)  # 等下载完成

    # 重命名为带日期的文件名
    if saved and saved.exists():
        today = datetime.now().strftime("%Y%m%d")
        new_name = DOWNLOAD_DIR / f"Seerfar-Product_{today}.csv"
        saved.rename(new_name)
        print(f"📁 已重命名: {saved.name} → {new_name.name}")
        saved = new_name

    try:
        await browser.screenshot("s9_export_done")
    except Exception:
        pass
    print(f"\n🎉 全流程完成！")
    print(f"   下载目录: {DOWNLOAD_DIR}")

    # 列出下载的文件
    files = sorted(DOWNLOAD_DIR.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]
    for f in files:
        size = f.stat().st_size
        print(f"   {f.name} ({size:,} bytes)")
    print()

    print("浏览器保持打开，Ctrl+C 关闭...")
    try:
        await asyncio.sleep(300)
    except KeyboardInterrupt:
        pass

    await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
