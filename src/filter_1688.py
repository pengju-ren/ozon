"""
1688 图搜结果相关性过滤 v2

改进:
  1. 俄语→中文 常用商品词映射（不需要翻译 API）
  2. 类目中文作为主要过滤信号（权重最高）
  3. 从标题提取规格词（数字+单位）
  4. 品牌精准匹配 + 变体匹配
  5. 分层加权打分，而非简单命中数
"""
import re
import logging
from typing import List, Dict, Set, Tuple

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# 俄语→中文 常用商品词映射（覆盖 Seerfar 高频类目）
# ------------------------------------------------------------------
RU_TO_CN = {
    # 燃油桶 / 容器
    "канистра": "油桶 汽油桶 柴油桶 桶 罐",
    "бак": "油箱 桶 罐",
    "ведро": "桶 水桶",
    "емкость": "容器 罐 桶",
    "бутылка": "瓶子 水瓶 酒瓶",
    # 电子
    "аккумулятор": "电池 充电宝 储能 电源",
    "зарядный": "充电 充电器 电源",
    "зарядное": "充电器 充电",
    "камера": "相机 摄像头",
    "принтер": "打印机",
    "ноутбук": "笔记本 电脑 笔记本电脑",
    "смартфон": "手机 智能手机",
    "телефон": "手机 电话",
    "наушники": "耳机",
    "колонка": "音箱 音响",
    "монитор": "显示器 屏幕",
    "планшет": "平板 平板电脑",
    "клавиатура": "键盘",
    "мышь": "鼠标",
    "роутер": "路由器",
    "маршрутизатор": "路由器",
    # 游戏
    "игровой": "游戏",
    "приставка": "游戏机 主机",
    "консоль": "游戏机 主机",
    # 工具 / 零件
    "карбюратор": "化油器 化油器总成",
    "генератор": "发电机 发电机总成",
    "двигатель": "发动机 引擎 马达",
    "запчасть": "配件 备件 零件",
    "инструмент": "工具",
    # 户外 / 家居
    "мебель": "家具",
    "садовый": "花园 户外",
    "кресло": "椅子 躺椅 沙发",
    "шезлонг": "躺椅 折叠椅 户外椅",
    "стол": "桌子 餐桌",
    "панель": "面板 板 太阳能板",
    "солнечный": "太阳能",
    # 其他
    "набор": "套装 套件 组合",
    "комплект": "套装 套件",
    "фитнес": "健身 运动",
    "браслет": "手环 手链",
    "часы": "手表 钟表",
    "пленка": "膜 薄膜",
    "стекло": "玻璃 钢化膜",
    "чехол": "保护壳 手机壳 保护套",
    "кожаный": "皮革 皮质",
    "сумка": "包 袋",
    "рюкзак": "背包 双肩包",
}

# 单位/规格模式
SPEC_PATTERN = re.compile(
    r'(\d+[\.,]?\d*)\s*(?:л|L|г|g|кг|kg|Вт|W|кВт|kW|'
    r'ГБ|GB|ТБ|TB|МП|MP|мАч|mAh|мм|mm|см|cm|м|m|'
    r'дюйм|Гц|Hz|об/мин|RPM|л\.с|hp)',
    re.IGNORECASE
)

_STOP = {"跨境", "货源", "一件代发", "现货", "批发", "厂家", "直销", "供应",
         "热卖", "爆款", "新款", "促销", "特价", "包邮", "定制", "加工",
         "适用于", "适用", "通用", "专用", "原装", "正品", "一件也是批发价",
         "厂家批发", "跨境专供", "源头厂家", "支持", "来图", "来样", "定制款"}


# ------------------------------------------------------------------
class ResultFilter:
    """根据 Ozon 商品信息过滤 1688 搜索结果"""

    def __init__(self, russian_title: str = "", brand: str = "",
                 category: str = ""):
        self.brand = brand.strip() if brand else ""
        self.brand_variants: Set[str] = set()
        self.cat_keywords: Set[str] = set()    # 类目中文词
        self.spec_keywords: Set[str] = set()   # 规格词
        self.latin_keywords: Set[str] = set()  # 拉丁/英文词
        self.cn_keywords: Set[str] = set()     # 俄语词典→中文词

        # ---- 1. 品牌 + 变体 ----
        if self.brand:
            b = self.brand.lower()
            self.brand_variants.add(b)
            # 常见品牌缩写/中文
            brand_aliases = {
                "dji": ["大疆"], "asus": ["华硕"], "msi": ["微星"],
                "xiaomi": ["小米"], "honor": ["荣耀"], "huawei": ["华为"],
                "samsung": ["三星"], "apple": ["苹果"], "lenovo": ["联想"],
                "dell": ["戴尔"], "hp": ["惠普"], "intel": ["英特尔"],
                "amd": ["超威"], "snapmaker": ["快造"],
                "rekidel": [], "firebat": ["火蝙蝠"],
            }
            for alias in brand_aliases.get(b, []):
                self.brand_variants.add(alias)

        # ---- 2. 类目中文 ----
        if category:
            lines = category.strip().split("\n")
            cat_cn = lines[0].strip() if lines else ""
            if cat_cn:
                # 按 2-4 字取词，过滤单字
                for seg_len in (4, 3, 2):
                    for i in range(len(cat_cn) - seg_len + 1):
                        seg = cat_cn[i:i + seg_len]
                        if seg not in _STOP and not seg.startswith(" ") and not seg.endswith(" "):
                            self.cat_keywords.add(seg)

        # ---- 3. 俄语标题 → 提取各种关键词 ----
        title_lower = (russian_title or "").lower()

        # 3a. 俄语词典匹配 → 中文词
        for ru_word, cn_words in RU_TO_CN.items():
            if ru_word in title_lower:
                for cw in cn_words.split():
                    if cw not in _STOP:
                        self.cn_keywords.add(cw)

        # 3b. 规格词（数字+单位）
        for m in SPEC_PATTERN.finditer(russian_title or ""):
            spec = m.group(0).lower().replace(",", ".")
            self.spec_keywords.add(spec)

        # 3c. 拉丁/英文词（品牌、型号等，>=3 字符）
        latin_words = re.findall(r'[A-Za-z][A-Za-z0-9+\-#]{2,}', russian_title or "")
        for w in latin_words:
            wl = w.lower()
            if wl not in _STOP and not wl.isdigit():
                self.latin_keywords.add(wl)

        # ---- 4. 清理 ----
        self.cat_keywords = {k for k in self.cat_keywords if len(k) >= 2}
        self.cn_keywords = {k for k in self.cn_keywords if len(k) >= 2}

        logger.debug(f"过滤词 — 类目: {self.cat_keywords}")
        logger.debug(f"过滤词 — CN: {self.cn_keywords}")
        logger.debug(f"过滤词 — 规格: {self.spec_keywords}")
        logger.debug(f"过滤词 — 拉丁: {self.latin_keywords}")
        logger.debug(f"过滤词 — 品牌: {self.brand_variants}")

    # ------------------------------------------------------------------
    def score(self, result_title: str) -> int:
        """计算相关性分数"""
        t = result_title.lower()
        s = 0

        # 权重: 品牌(6) > 类目(4) > 中文词典(3) > 规格(2) > 拉丁(1)

        # 品牌
        for bv in self.brand_variants:
            if bv in t:
                s += 6
                break

        # 类目
        for kw in self.cat_keywords:
            if kw in t:
                s += 4

        # 俄语→中文词典
        for kw in self.cn_keywords:
            if kw in t:
                s += 3

        # 规格
        for spec in self.spec_keywords:
            # 单位部分在 1688 标题中可能有空格: "20 л" vs "20л"
            val, unit = _split_spec(spec)
            if unit and val:
                if f"{val}{unit}" in t or f"{val} {unit}" in t.replace(" ", ""):
                    s += 2
                    continue
            if spec in t:
                s += 2

        # 拉丁/英文
        for kw in self.latin_keywords:
            if len(kw) >= 4 and kw in t:
                s += 1  # 长词权重

        return s

    # ------------------------------------------------------------------
    def filter(self, products: List[Dict], min_score: int = 2) -> Tuple[List[Dict], List[Dict]]:
        """过滤，阈值默认 2（至少命中一个类目词或品牌）"""
        passed, rejected = [], []

        for p in products:
            d = p.get("data", {}) if isinstance(p, dict) else {}
            title = d.get("title", "") or p.get("title", "")
            s = self.score(title)
            if s >= min_score:
                p["_relevance_score"] = s
                passed.append(p)
            else:
                rejected.append(p)

        passed.sort(key=lambda x: x.get("_relevance_score", 0), reverse=True)

        logger.info(
            f"过滤: {len(passed)} 通过 / {len(rejected)} 淘汰 "
            f"(阈值={min_score})"
        )
        return passed, rejected

    # ------------------------------------------------------------------
    @classmethod
    def from_ozon_row(cls, title_ru: str, brand: str, category: str) -> "ResultFilter":
        return cls(russian_title=title_ru, brand=brand, category=category)


# ------------------------------------------------------------------
def _split_spec(spec: str) -> Tuple[str, str]:
    """拆分规格：'20л' → ('20', 'л')"""
    m = re.match(r'([\d.]+)\s*([а-яёa-z]+)', spec, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).lower()
    return spec, ""
