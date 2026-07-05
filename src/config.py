"""
配置模块 - 管理API密钥、路径和搜索参数
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent

# 加载 .env 文件
load_dotenv(ROOT_DIR / ".env")

# ============================================================
# API 配置 (OneBound / Open Claw)
# 注册: https://open-claw.cn 获取免费 500次/天
# ============================================================
ONEBOUND_API_KEY = os.getenv("ONEBOUND_API_KEY", "")
ONEBOUND_API_SECRET = os.getenv("ONEBOUND_API_SECRET", "")

# OneBound API 网关地址
ONEBOUND_BASE_URL = "https://api-gw.onebound.cn/1688"

# ============================================================
# 汇率配置
# ============================================================
RUB_TO_CNY = float(os.getenv("RUB_TO_CNY", "0.078"))

# ============================================================
# 路径配置
# ============================================================
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 默认输入文件（按日期匹配最新）
DEFAULT_INPUT_FILE = None  # 运行时指定

# 输出文件
DEFAULT_OUTPUT_FILE = OUTPUT_DIR / "1688_match_result.xlsx"

# ============================================================
# 搜索参数
# ============================================================
# 每个商品搜索的页数
SEARCH_PAGES = 2

# 每页结果数（最大50）
PAGE_SIZE = 30

# 图片搜索相似度阈值（0-1，低于此值的结果被过滤）
IMAGE_SIMILARITY_THRESHOLD = 0.5

# 每个Ozon商品保留的最佳1688匹配数
TOP_MATCHES_PER_PRODUCT = 5

# 请求间隔（秒），避免触发限流
REQUEST_DELAY = 1.5

# 最大重试次数
MAX_RETRIES = 3

# 请求超时（秒）
REQUEST_TIMEOUT = 30

# ============================================================
# 翻译配置
# ============================================================
# CSV 翻译文件（大模型预翻译的俄语→中文映射）
CSV_TRANSLATION_FILE = os.getenv("CSV_TRANSLATION_FILE", "")

# ============================================================
# 输入 Excel 列名映射
# ============================================================
# Excel 中的列名（需与实际的列名或列索引对应）
COL_RANK = "排名"
COL_IMAGE = "主图"
COL_TITLE = "标题"
COL_URL = "详情页地址"
COL_SKU = "SKU"
COL_BRAND = "品牌"
COL_CATEGORY = "类目"
COL_PRICE = "售价"
COL_SALES = "销量"
COL_REVENUE = "销售额"
COL_MARGIN = "毛利率"
COL_WEIGHT = "重量"
COL_VOLUME = "体积"
COL_STORE = "店铺"
