"""
翻译模块 - 俄语标题 → 中文搜索关键词
使用大模型预翻译的 CSV 文件进行翻译查找
"""
import csv
import re
import logging
from typing import List

logger = logging.getLogger(__name__)


class Translator:
    """
    俄语→中文翻译器
    从大模型预翻译的 CSV 文件中查找翻译结果
    """

    def __init__(self, csv_path: str = ""):
        self._dict: dict = {}
        if csv_path:
            self._load_csv(csv_path)
        else:
            logger.warning("未配置CSV翻译文件，翻译将返回空")

    def _load_csv(self, csv_path: str):
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # 跳过表头
                for row in reader:
                    if len(row) >= 2 and row[0].strip() and row[1].strip():
                        self._dict[row[0].strip()] = row[1].strip()
            logger.info(f"从CSV加载了 {len(self._dict)} 条大模型翻译")
        except FileNotFoundError:
            logger.warning(f"CSV翻译文件不存在: {csv_path}")
        except Exception as e:
            logger.warning(f"加载CSV翻译失败: {e}")

    def translate(self, text: str) -> str:
        """从CSV查找翻译"""
        if not text or not text.strip():
            return ""
        return self._dict.get(text.strip(), "")

    def translate_batch(self, texts: List[str]) -> List[str]:
        """批量翻译"""
        return [self.translate(t) for t in texts]

    def extract_keywords(self, russian_title: str, brand: str = "") -> str:
        """从俄语标题提取中文搜索关键词"""
        full_cn = self.translate(russian_title)
        if not full_cn:
            return ""

        keywords = full_cn

        # 去掉品牌名
        if brand and brand.strip():
            brand_cn = self.translate(brand.strip())
            if brand_cn and brand_cn in keywords:
                keywords = keywords.replace(brand_cn, "").strip()

        # 清理
        keywords = re.sub(r'\s+', ' ', keywords).strip()
        keywords = re.sub(r'[а-яА-ЯёЁ]', '', keywords).strip()

        # 截断过长文本
        if len(keywords) > 30:
            trunc = keywords[:30]
            last_space = trunc.rfind(' ')
            keywords = trunc[:last_space] if last_space > 10 else trunc

        return keywords or full_cn[:30]

    def extract_search_queries(
        self, russian_title: str, category: str = "", brand: str = ""
    ) -> List[str]:
        """生成多个搜索查询变体"""
        queries = []
        main_keyword = self.extract_keywords(russian_title, brand)
        if main_keyword:
            queries.append(main_keyword)

        if category and category.strip():
            cat_cn = (
                category.split('\n')[0].strip()
                if '\n' in category
                else category
            )
            if cat_cn and cat_cn not in queries:
                queries.append(cat_cn)

        if main_keyword:
            words = main_keyword.split()
            if len(words) >= 2:
                short_query = ' '.join(words[:3])
                if short_query not in queries:
                    queries.append(short_query)

        return queries
