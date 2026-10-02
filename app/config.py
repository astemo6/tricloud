"""应用配置：全部来自环境变量，无硬编码密钥。"""
import os

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
DATA_DIR = os.path.abspath(DATA_DIR)

PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
FERNET_KEY = os.environ.get("FERNET_KEY", "")  # 为空则首次启动时生成并存到 data/fernet.key

SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "7200"))  # 2 小时滑动过期
JOB_WORKERS = int(os.environ.get("JOB_WORKERS", "4"))

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
