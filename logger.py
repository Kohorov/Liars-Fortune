import sys
from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>")
logger.add("logs/bot.log", rotation="10 MB", retention="14 days", level="DEBUG", encoding="utf-8")
