#!/usr/bin/env python3
"""
1688 官方 API 快速测试
测试你的 AppKey/Secret 是否能正常调用搜索接口

用法:
    # 1. 先在 .env 中填入你的 AppKey 和 AppSecret:
    #    ALIBABA_APP_KEY=你的AppKey
    #    ALIBABA_APP_SECRET=你的AppSecret

    # 2. 运行测试
    python test_1688_official.py --keyword "折叠躺椅"
"""
import sys
import json
import asyncio
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.searcher_1688_official import Alibaba1688Searcher


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", default="折叠躺椅", help="搜索关键词")
    parser.add_argument("--offer-id", default="", help="测试商品详情 (offerId)")
    args = parser.parse_args()

    searcher = Alibaba1688Searcher()
    print(f"AppKey 已配置: {bool(searcher.app_key)}")
    print(f"AppSecret 已配置: {bool(searcher.app_secret)}")

    if not searcher.app_key:
        print("\n❌ 请先在 .env 中设置 ALIBABA_APP_KEY 和 ALIBABA_APP_SECRET")
        return

    # 1. 测试搜索
    print(f"\n{'='*60}")
    print(f"1️⃣  测试关键词搜索: {args.keyword}")
    print("="*60)
    results = await searcher.search_by_keyword(args.keyword)

    if results:
        print(f"\n✅ 搜索成功! 找到 {len(results)} 个商品:\n")
        for i, p in enumerate(results[:5]):
            print(f"  [{i+1}] {p.display_price} | {p.title[:50]}")
            print(f"      起批: {p.min_order} | 店铺: {p.shop_name}")
            if p.detail_url:
                print(f"      链接: {p.detail_url}")
            print()
    else:
        print("\n⚠️ 没有返回结果，可能原因:")
        print("  1. API 权限未开通 → 去 open.1688.com 申请 alibaba.offer.search")
        print("  2. AppKey/Secret 不正确")
        print("  3. 账号未完成企业认证")

    # 2. 测试商品详情（如果提供了offerId）
    if args.offer_id:
        print(f"\n{'='*60}")
        print(f"2️⃣  测试商品详情: {args.offer_id}")
        print("="*60)
        detail = searcher.get_item_detail(args.offer_id)
        if detail:
            print(f"\n✅ 详情获取成功:")
            print(json.dumps(detail, ensure_ascii=False, indent=2)[:2000])
        else:
            print("\n⚠️ 详情获取失败")


if __name__ == "__main__":
    asyncio.run(main())
