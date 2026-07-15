"""
标题翻译 — CSV 字典查找 + 关键字提取
国内环境 Google Translate 不通，用预翻译 CSV + 类目双语 + 品牌词做关键词
"""
import csv
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRANSLATION_CSV = ROOT / "output" / "titles_for_translation.csv"


class TitleTranslator:
    """俄语标题 → 中文关键词提取器"""

    def __init__(self, translation_csv: Path = None):
        self._dict: Dict[str, str] = {}
        csv_path = translation_csv or DEFAULT_TRANSLATION_CSV
        if csv_path.exists():
            self._load(csv_path)
            logger.info(f"翻译字典加载: {len(self._dict)} 条")

    def _load(self, path: Path):
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ru = (row.get("俄语原文") or "").strip()
                zh = (row.get("中文翻译") or "").strip()
                if ru and zh:
                    self._dict[ru] = zh

    # ------------------------------------------------------------------
    # 翻译
    # ------------------------------------------------------------------
    def translate(self, russian_title: str) -> str:
        """
        翻译俄语标题 → 中文
        1. 先查 CSV 字典
        2. 命中的话返回中文
        3. 未命中则提取品牌词 + 规格词 + 类目翻译作为兜底
        """
        title = russian_title.strip()
        if not title:
            return ""

        # 精确匹配
        if title in self._dict:
            return self._dict[title]

        # 前缀匹配（有些标题有细微差异）
        for ru, zh in self._dict.items():
            if ru[:40] == title[:40]:
                return zh

        # 兜底：返回空，由上层用 extract_keywords 处理
        return ""

    # ------------------------------------------------------------------
    # 关键词提取（用于过滤）
    # ------------------------------------------------------------------
    BRAND_KW = re.compile(
        r'\b(?:Intel|AMD|Ryzen|Radeon|NVIDIA|GeForce|RTX|GTX|'
        r'Core|Ultra|Snapdragon|MediaTek|Dimensity|Apple|M[0-9]|'
        r'ASUS|ROG|MSI|Lenovo|ThinkPad|ThinkBook|Dell|HP|Acer|'
        r'Samsung|Xiaomi|Huawei|Honor|OPPO|vivo|OnePlus|realme|'
        r'Google|Microsoft|Surface|MacBook|iPad|iPhone|'
        r'Logitech|Razer|Corsair|SteelSeries|HyperX|'
        r'Sony|Bose|JBL|Sennheiser|Anker|UGREEN|Baseus)\b',
        re.IGNORECASE
    )

    @staticmethod
    def extract_keywords(russian_title: str, brand: str = "",
                         category: str = "") -> List[str]:
        """
        从标题 + 品牌 + 类目中提取中文关键词（用于 1688 结果过滤）

        返回: 去重后的关键词列表
        """
        keywords = set()

        # 1. 品牌词
        if brand and brand.strip():
            keywords.add(brand.strip().lower())

        # 2. 从标题中提取品牌/型号拉丁词
        latin = re.findall(r'[A-Za-z0-9+\-]{3,}', russian_title or "")
        for w in latin:
            # 跳过纯数字
            if w.isdigit():
                continue
            keywords.add(w.lower())

        # 3. 类目中的中文（第一行通常是中文）
        if category:
            lines = category.strip().split("\n")
            if lines:
                cn_cat = lines[0].strip()
                if cn_cat and re.search(r'[一-鿿]', cn_cat):
                    # 中文类目分词（简单按 2-5 字滑动）
                    for i in range(len(cn_cat)):
                        for seg_len in (2, 3, 4):
                            seg = cn_cat[i:i + seg_len]
                            if len(seg) == seg_len:
                                keywords.add(seg)

        # 4. 如果有翻译，也加进来
        # 去除俄语西里尔字母部分，剩下的英文词也可做关键词
        non_cyrillic = re.sub(r'[А-Яа-яЁё]+', ' ', russian_title)
        non_cyrillic_words = re.findall(r'[A-Za-z0-9+\-]{3,}', non_cyrillic)
        for w in non_cyrillic_words:
            if not w.isdigit():
                keywords.add(w.lower())

        # 过滤太通用的词
        stop = {'the', 'and', 'for', 'pro', 'max', 'mini', 'new', 'with',
                'size', 'model', 'type', 'use', 'all', 'one', 'set', 'kit',
                'box', 'pack', 'bag', 'case', 'card', 'made', 'hot', 'top',
                'best', 'sale', 'newest', 'latest', 'high', 'low', 'big',
                'small', 'large', 'medium', 'lite', 'plus', 'ultra', 'version',
                'original', 'brand', 'quality', 'good', 'nice', 'super'}
        keywords = {k for k in keywords if k not in stop}

        return list(keywords)
