from pathlib import Path
import aiofiles
import aiohttp
import time
from astrbot import logger

SAVED_SONGS_DIR = Path("data", "plugin_data", "astrbot_plugin_music", "songs")
SAVED_SONGS_DIR.mkdir(parents=True, exist_ok=True)

async def download_image(url: str) -> bytes | None:
    """下载图片"""
    start_time = time.time()
    logger.info(f"[工具图片下载开始] URL: {url}")
    
    url = url.replace("https://", "http://")
    try:
        async with aiohttp.ClientSession() as client:
            response = await client.get(url)
            img_bytes = await response.read()
            
            execution_time = time.time() - start_time
            logger.info(f"[工具图片下载完成] URL: {url}, 耗时: {execution_time:.2f}秒, 图片大小: {len(img_bytes)}字节")
            
            return img_bytes
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"[工具图片下载失败] URL: {url}, 耗时: {execution_time:.2f}秒, 错误: {e}")
        return None

async def download_song(self, url: str, title: str) -> str | None:
    """下载歌曲"""
    start_time = time.time()
    logger.info(f"[歌曲下载开始] 标题: {title}, URL: {url}")
    
    file_path = str(SAVED_SONGS_DIR / f"{title}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    file_size = 0
                    async with aiofiles.open(file_path, "wb") as f:
                        # 流式写入文件
                        while True:
                            chunk = await response.content.read(1024)
                            if not chunk:
                                break
                            await f.write(chunk)
                            file_size += len(chunk)
                    
                    execution_time = time.time() - start_time
                    logger.info(f"[歌曲下载完成] 标题: {title}, 耗时: {execution_time:.2f}秒, 文件大小: {file_size}字节, 保存路径: {file_path}")
                    return file_path
                else:
                    execution_time = time.time() - start_time
                    logger.error(f"[歌曲下载失败] 标题: {title}, 耗时: {execution_time:.2f}秒, HTTP状态码: {response.status}")
                    return None
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"[歌曲下载异常] 标题: {title}, 耗时: {execution_time:.2f}秒, 错误: {e}")
        return None

def format_time(duration_ms):
    """格式化歌曲时长"""
    duration = duration_ms // 1000

    hours = duration // 3600
    minutes = (duration % 3600) // 60
    seconds = duration % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"
