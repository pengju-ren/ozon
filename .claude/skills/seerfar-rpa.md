---
name: seerfar-rpa
description: |
  Seerfar 热销榜单选品全自动 RPA。
  自动登录 → 筛选条件（RFBS/近30天）→ 毛利率降序 → 导出2000条CSV。
  触发词: 跑Seerfar、Seerfar数据、热销榜单、Ozon选品、seerfar rpa
model: haiku
---

# Seerfar RPA

自动抓取 Seerfar 热销榜单数据。

**路径**: `rpa/seerfar_full.py`

## 使用方式

用户说以下任意关键词时触发：
- "跑 Seerfar" / "抓 Seerfar 数据" / "热销榜单"
- "Ozon 选品" / "seerfar rpa"

## 执行

```bash
python3 -u rpa/seerfar_full.py
```

## 流程

| 步骤 | 操作 |
|------|------|
| 1 | 打开 seerfar.com 登录 |
| 2 | 悬停"功能" → 点击"热销榜单选品" |
| 3 | 点击"进阶"展开筛选面板 |
| 4 | 配送方式 → RFBS，上架时间 → 近30天 |
| 5 | 点击"查询"等表格加载 |
| 6 | 点击毛利率列头降序排列 |
| 7 | 导出 CSV（2000条），重命名 `Seerfar-Product_YYYYMMDD.csv` |

## 输出

- 文件: `output/downloads/Seerfar-Product_YYYYMMDD.csv`
- 截图: `output/downloads/s1~s9_*.png`（每步一张，方便排错）

## 依赖

- Playwright
- 引擎封装: `rpa/browser.py`（RPABrowser 类）
