
import random
import traceback
import os
import asyncio
import aiofiles
import aiohttp
import hashlib
import time
from astrbot.api.event import filter, AstrMessageEvent
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Record
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.utils.session_waiter import (
    session_waiter,
    SessionController,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot import logger
from data.plugins.astrbot_plugin_music.draw import draw_lyrics
from data.plugins.astrbot_plugin_music.utils import format_time


@register(
    "astrbot_plugin_music",
    "Zhalslar",
    "音乐搜索、热评",
    "1.0.1",
    "https://github.com/Zhalslar/astrbot_plugin_music",
)
class MusicPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        
        # 验证并加载配置
        self._validate_and_load_config(config)
        
        # 音频缓存目录
        self.cache_dir = "data/plugins/astrbot_plugin_music/cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # elif self.default_api == "tencent":
        #     from .api import TencentMusicAPI
        #     self.api = TencentMusicAPI()
    
    def _validate_and_load_config(self, config: AstrBotConfig):
        """验证并加载配置，提供合理的默认值和错误处理"""
        
        # 默认API配置验证
        valid_apis = ["netease", "qqmusic", "kugou", "netease_nodejs"]
        self.default_api = config.get("default_api", "netease")
        if self.default_api not in valid_apis:
            logger.warning(f"无效的默认API配置: {self.default_api}，使用默认值: netease")
            self.default_api = "netease"
        
        # 网易云nodejs服务的默认端口
        self.nodejs_base_url = config.get(
            "nodejs_base_url", "http://netease_cloud_music_api:3000"
        )
        if not isinstance(self.nodejs_base_url, str) or not self.nodejs_base_url:
            logger.warning("无效的nodejs_base_url配置，使用默认值")
            self.nodejs_base_url = "http://netease_cloud_music_api:3000"
        
        # 根据API类型初始化对应的API实例
        if self.default_api == "netease":
            from .api import NetEaseMusicAPI
            self.api = NetEaseMusicAPI()
        elif self.default_api == "netease_nodejs":
            from .api import NetEaseMusicAPINodeJs
            self.api = NetEaseMusicAPINodeJs(base_url=self.nodejs_base_url)
        else:
            # 对于QQ音乐和酷狗音乐，暂时使用网易云API作为基础
            from .api import NetEaseMusicAPI
            self.api = NetEaseMusicAPI()
            logger.info(f"使用网易云API作为{self.default_api}的基础实现")
        
        # 缓存配置验证
        self.cache_enabled = bool(config.get("cache_enabled", True))
        
        cache_max_size = config.get("cache_max_size", 500)
        if not isinstance(cache_max_size, int) or cache_max_size < 10:
            logger.warning(f"无效的缓存大小配置: {cache_max_size}，使用默认值: 500MB")
            self.cache_max_size = 500
        else:
            self.cache_max_size = cache_max_size
        
        cache_max_age = config.get("cache_max_age", 7)
        if not isinstance(cache_max_age, int) or cache_max_age < 1:
            logger.warning(f"无效的缓存保存时间配置: {cache_max_age}，使用默认值: 7天")
            self.cache_max_age = 7
        else:
            self.cache_max_age = cache_max_age
        
        # 选择模式验证
        valid_select_modes = ["text", "image"]
        self.select_mode = config.get("select_mode", "text")
        if self.select_mode not in valid_select_modes:
            logger.warning(f"无效的选择模式配置: {self.select_mode}，使用默认值: text")
            self.select_mode = "text"
        
        # 发送模式验证
        valid_send_modes = ["text", "record", "card", "forward"]
        self.send_mode = config.get("send_mode", "card")
        if self.send_mode not in valid_send_modes:
            logger.warning(f"无效的发送模式配置: {self.send_mode}，使用默认值: card")
            self.send_mode = "card"
        
        # 布尔类型配置验证
        self.enable_comments = bool(config.get("enable_comments", True))
        self.enable_lyrics = bool(config.get("enable_lyrics", False))
        self.enable_record_mode = bool(config.get("enable_record_mode", False))
        
        # 超时时间验证
        timeout = config.get("timeout", 30)
        if not isinstance(timeout, int) or timeout < 5 or timeout > 300:
            logger.warning(f"无效的超时时间配置: {timeout}，使用默认值: 30秒")
            self.timeout = 30
        else:
            self.timeout = timeout
        
        # 记录配置信息
        logger.info(f"音乐插件配置加载完成: API={self.default_api}, 选择模式={self.select_mode}, 发送模式={self.send_mode}")
        logger.info(f"缓存配置: 启用={self.cache_enabled}, 最大大小={self.cache_max_size}MB, 保存时间={self.cache_max_age}天")
        logger.info(f"功能配置: 评论={self.enable_comments}, 歌词={self.enable_lyrics}, 语音模式={self.enable_record_mode}, 超时={self.timeout}秒")
    
    def get_config_summary(self) -> dict:
        """获取配置摘要信息"""
        return {
            "default_api": self.default_api,
            "nodejs_base_url": self.nodejs_base_url,
            "select_mode": self.select_mode,
            "send_mode": self.send_mode,
            "cache_enabled": self.cache_enabled,
            "cache_max_size": self.cache_max_size,
            "cache_max_age": self.cache_max_age,
            "enable_comments": self.enable_comments,
            "enable_lyrics": self.enable_lyrics,
            "enable_record_mode": self.enable_record_mode,
            "timeout": self.timeout
        }
    
    async def download_audio(self, url: str, filename: str, force_download: bool = False) -> str:
        """下载音频文件到本地缓存"""
        start_time = time.time()
        logger.info(f"[音频下载开始] URL: {url}, 文件名: {filename}, 强制下载: {force_download}")
        
        filepath = os.path.join(self.cache_dir, filename)
        
        # 如果缓存未启用，直接返回URL
        if not self.cache_enabled:
            execution_time = time.time() - start_time
            logger.info(f"[音频下载完成-缓存禁用] 耗时: {execution_time:.2f}秒, 返回原始URL")
            return url
        
        # 确保缓存目录存在
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 如果文件已存在且不需要强制下载，直接返回路径
        if os.path.exists(filepath) and not force_download:
            logger.info(f"使用缓存文件: {filepath}")
            # 更新文件修改时间
            os.utime(filepath, (time.time(), time.time()))
            execution_time = time.time() - start_time
            logger.info(f"[音频下载完成-缓存命中] 耗时: {execution_time:.2f}秒, 文件: {filename}")
            return filepath
        
        # 智能缓存查找：尝试查找相同歌曲ID的其他缓存文件
        song_id = filename.split('_')[0] if '_' in filename else ""
        if song_id and not force_download:
            # 确保缓存目录存在且可访问
            if os.path.exists(self.cache_dir):
                # 查找相同歌曲ID的缓存文件（优先返回.wav文件）
                wav_files = []
                mp3_files = []
                
                for existing_file in os.listdir(self.cache_dir):
                    if existing_file.startswith(song_id + '_'):
                        if existing_file.endswith('.wav'):
                            wav_files.append(existing_file)
                        elif existing_file.endswith('.mp3'):
                            mp3_files.append(existing_file)
                
                # 优先返回.wav文件
                for file_list in [wav_files, mp3_files]:
                    for existing_file in file_list:
                        existing_path = os.path.join(self.cache_dir, existing_file)
                        if os.path.exists(existing_path):
                            logger.info(f"找到相同歌曲的缓存文件，使用: {existing_file}")
                            # 更新文件修改时间
                            os.utime(existing_path, (time.time(), time.time()))
                            execution_time = time.time() - start_time
                            logger.info(f"[音频下载完成-智能缓存] 耗时: {execution_time:.2f}秒, 文件: {existing_file}")
                            return existing_path
        
        # 在下载前触发自动清理机制
        await self.auto_cleanup_cache()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        async with aiofiles.open(filepath, 'wb') as f:
                            await f.write(await response.read())
                        
                        # 获取文件大小
                        file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
                        file_size_mb = file_size / (1024 * 1024)
                        
                        # 更新文件修改时间
                        os.utime(filepath, (time.time(), time.time()))
                        
                        execution_time = time.time() - start_time
                        logger.info(f"[音频下载完成-网络下载] 耗时: {execution_time:.2f}秒, 文件: {filename}, 大小: {file_size_mb:.2f}MB")
                        return filepath
                    else:
                        execution_time = time.time() - start_time
                        logger.error(f"[音频下载失败] 耗时: {execution_time:.2f}秒, 状态码: {response.status}, URL: {url}")
                        return url  # 返回原始URL作为降级方案
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[音频下载异常] 耗时: {execution_time:.2f}秒, URL: {url}, 错误: {e}")
            return url  # 返回原始URL作为降级方案
    
    def get_cache_filename(self, song_id: str, audio_url: str) -> str:
        """生成缓存文件名"""
        # 使用歌曲ID和音频URL的哈希值作为文件名
        url_hash = hashlib.md5(audio_url.encode()).hexdigest()[:8]
        return f"{song_id}_{url_hash}.mp3"
    
    def get_wav_cache_filename(self, song_id: str, audio_url: str) -> str:
        """生成WAV缓存文件名"""
        # 使用歌曲ID和音频URL的哈希值作为文件名
        url_hash = hashlib.md5(audio_url.encode()).hexdigest()[:8]
        return f"{song_id}_{url_hash}.wav"
    
    def get_cache_file_path(self, filename: str) -> str:
        """获取缓存文件完整路径"""
        return os.path.join(self.cache_dir, filename)
    
    async def cleanup_cache(self):
        """清理过期缓存文件"""
        if not os.path.exists(self.cache_dir):
            return
            
        import time
        current_time = time.time()
        max_age_seconds = self.cache_max_age * 24 * 60 * 60
        
        # 计算当前缓存大小
        total_size = 0
        cache_files = []
        
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            if os.path.isfile(filepath) and filename.endswith(('.mp3', '.wav')):
                file_stat = os.stat(filepath)
                file_size = file_stat.st_size
                file_age = current_time - file_stat.st_mtime
                
                cache_files.append({
                    'path': filepath,
                    'size': file_size,
                    'age': file_age,
                    'mtime': file_stat.st_mtime
                })
                total_size += file_size
        
        # 按修改时间排序（最旧的在前）
        cache_files.sort(key=lambda x: x['mtime'])
        
        # 清理过期文件
        deleted_files = []
        for file_info in cache_files:
            if file_info['age'] > max_age_seconds:
                try:
                    os.remove(file_info['path'])
                    deleted_files.append(file_info['path'])
                    total_size -= file_info['size']
                    logger.info(f"清理过期缓存文件: {os.path.basename(file_info['path'])}")
                except Exception as e:
                    logger.warning(f"删除过期缓存文件失败 {file_info['path']}: {e}")
        
        # 如果缓存大小仍然超过限制，继续清理最旧的文件
        max_size_bytes = self.cache_max_size * 1024 * 1024
        while total_size > max_size_bytes and cache_files:
            file_info = cache_files.pop(0)
            if file_info['path'] not in deleted_files:
                try:
                    os.remove(file_info['path'])
                    deleted_files.append(file_info['path'])
                    total_size -= file_info['size']
                    logger.info(f"清理超限缓存文件: {os.path.basename(file_info['path'])}")
                except Exception as e:
                    logger.warning(f"删除超限缓存文件失败 {file_info['path']}: {e}")
        
        if deleted_files:
            logger.info(f"缓存清理完成，共删除 {len(deleted_files)} 个文件")
        
        return {
            "deleted_files": len(deleted_files),
            "remaining_files": len(cache_files) - len(deleted_files),
            "total_size_before": total_size + sum(f['size'] for f in deleted_files),
            "total_size_after": total_size
        }
    
    async def auto_cleanup_cache(self):
        """自动清理缓存（在下载音频前调用）"""
        try:
            cache_info = await self.get_cache_info()
            total_size_mb = cache_info["total_size"] / (1024 * 1024)
            
            # 如果缓存大小超过限制的80%，触发自动清理
            if total_size_mb > self.cache_max_size * 0.8:
                logger.info(f"缓存大小({total_size_mb:.2f}MB)超过限制的80%，触发自动清理")
                result = await self.cleanup_cache()
                
                if result["deleted_files"] > 0:
                    logger.info(f"自动清理完成，删除{result['deleted_files']}个文件，剩余{result['remaining_files']}个文件")
                
                return True
            
            # 检查是否有过期文件
            import time
            current_time = time.time()
            max_age_seconds = self.cache_max_age * 24 * 60 * 60
            
            for filename in os.listdir(self.cache_dir):
                filepath = os.path.join(self.cache_dir, filename)
                if os.path.isfile(filepath) and filename.endswith(('.mp3', '.wav')):
                    file_stat = os.stat(filepath)
                    file_age = current_time - file_stat.st_mtime
                    
                    if file_age > max_age_seconds:
                        logger.info("发现过期缓存文件，触发自动清理")
                        result = await self.cleanup_cache()
                        
                        if result["deleted_files"] > 0:
                            logger.info(f"自动清理完成，删除{result['deleted_files']}个文件")
                        
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"自动清理缓存时出错: {e}")
            return False
    
    async def get_cache_info(self) -> dict:
        """获取缓存统计信息"""
        if not os.path.exists(self.cache_dir):
            return {"total_files": 0, "total_size": 0, "mp3_files": 0, "wav_files": 0}
        
        total_size = 0
        mp3_count = 0
        wav_count = 0
        
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            if os.path.isfile(filepath):
                if filename.endswith('.mp3'):
                    mp3_count += 1
                elif filename.endswith('.wav'):
                    wav_count += 1
                
                total_size += os.path.getsize(filepath)
        
        return {
            "total_files": mp3_count + wav_count,
            "total_size": total_size,
            "mp3_files": mp3_count,
            "wav_files": wav_count
        }
    
    async def convert_audio_to_wav(self, input_path: str, output_path: str) -> bool:
        """将音频转换为wav格式（需要安装ffmpeg）"""
        start_time = time.time()
        logger.info(f"[音频转换开始] 输入: {input_path}, 输出: {output_path}")
        
        try:
            import subprocess
            result = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', input_path, '-acodec', 'pcm_s16le', 
                '-ar', '16000', '-ac', '1', output_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                # 获取输出文件大小
                output_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
                output_size_mb = output_size / (1024 * 1024)
                
                execution_time = time.time() - start_time
                logger.info(f"[音频转换成功] 耗时: {execution_time:.2f}秒, 输出文件: {output_path}, 大小: {output_size_mb:.2f}MB")
                return True
            else:
                execution_time = time.time() - start_time
                logger.error(f"[音频转换失败] 耗时: {execution_time:.2f}秒, 输入: {input_path}, 错误: {stderr.decode()}")
                return False
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[音频转换异常] 耗时: {execution_time:.2f}秒, 输入: {input_path}, 错误: {e}")
            return False
        # elif self.default_api == "kugou":
        #     from .api import KuGouMusicAPI
        #     self.api = KuGouMusicAPI()

        # 选择模式
        self.select_mode = config.get("select_mode", "text")

        # 发送模式
        self.send_mode = config.get("send_mode", "card")

        # 是否启用评论
        self.enable_comments = config.get("enable_comments", True)

        # 是否启用歌词
        self.enable_lyrics = config.get("enable_lyrics", False)

        # 是否启用语音模式
        self.enable_record_mode = config.get("enable_record_mode", False)

        # 等待超时时长
        self.timeout = config.get("timeout", 30)

    @filter.command("点歌")
    async def search_song(self, event: AstrMessageEvent):
        """点歌功能 - 支持多音源搜索"""
        start_time = time.time()
        try:
            logger.info(f"[点歌开始] 用户: {event.get_sender_id()}, 关键词: {event.message_str}")
            
            # 获取搜索关键词和音源类型
            keyword = event.message_str.replace("点歌", "").strip()
            
            # 解析音源类型
            source_type = "netease"  # 默认网易云
            if "qq" in keyword.lower() or "QQ" in keyword:
                source_type = "qq"
                keyword = keyword.replace("qq", "").replace("QQ", "").strip()
            elif "酷狗" in keyword or "kugou" in keyword.lower():
                source_type = "kugou"
                keyword = keyword.replace("酷狗", "").replace("kugou", "").strip()
            elif "网易" in keyword or "网抑云" in keyword:
                source_type = "netease"
                keyword = keyword.replace("网易", "").replace("网抑云", "").strip()
            
            if not keyword:
                yield event.plain_result("请输入要搜索的歌曲名称\n支持音源: QQ音乐、网易云、酷狗音乐")
                return
            
            # 调用对应音源的API搜索歌曲
            songs = []
            if source_type == "netease":
                songs = await self.api.fetch_data(keyword=keyword)
            elif source_type == "qq":
                songs = await self._fetch_qq_music(keyword)
            elif source_type == "kugou":
                songs = await self._fetch_kugou_music(keyword)
            
            if not songs:
                yield event.plain_result(f"未在{self._get_source_name(source_type)}找到相关歌曲，请尝试其他关键词")
                return
            
            # 显示歌曲列表供用户选择
            await self._send_selection(event, songs, source_type)
            
            # 等待用户选择
            @session_waiter(timeout=self.timeout, record_history_chains=False)  # type: ignore  # noqa: F821
            async def empty_mention_waiter(
                controller: SessionController, event: AstrMessageEvent
            ):
                try:
                    index = event.message_str
                    if not index.isdigit() or int(index) < 1 or int(index) > len(songs):
                        return
                    selected_song = songs[int(index) - 1]
                    # 直接同步执行发送操作，避免异步任务被其他插件中断
                    await self._send_song(event=event, song=selected_song, source_type=source_type)
                    controller.stop()
                except Exception as e:
                    logger.error(f"点歌选择过程发生错误: {e}")
                    logger.error(traceback.format_exc())

            try:
                await empty_mention_waiter(event)  # type: ignore
            except TimeoutError as _:
                yield event.plain_result("点歌超时！")
            except Exception as e:
                logger.error(f"点歌会话等待发生错误: {e}")
                logger.error(traceback.format_exc())
                yield event.plain_result("点歌过程中发生错误，请稍后重试~")

            event.stop_event()
        except Exception as e:
            logger.error(f"点歌命令执行发生错误: {e}")
            logger.error(traceback.format_exc())
            execution_time = time.time() - start_time
            logger.error(f"[点歌失败] 用户: {event.get_sender_id()}, 耗时: {execution_time:.2f}秒, 错误: {e}")
            yield event.plain_result("点歌过程中发生错误，请稍后重试~")
            event.stop_event()
        
        # 记录成功执行的性能信息
        execution_time = time.time() - start_time
        logger.info(f"[点歌完成] 用户: {event.get_sender_id()}, 耗时: {execution_time:.2f}秒")
    
    @filter.command("音乐配置")
    async def show_config(self, event: AstrMessageEvent):
        """显示当前音乐插件配置信息"""
        try:
            config_summary = self.get_config_summary()
            cache_info = await self.get_cache_info()
            
            # 构建配置信息消息
            message = "🎵 音乐插件配置信息\n\n"
            
            # 基本配置
            message += f"📊 默认音源: {config_summary['default_api']}\n"
            message += f"🎯 选择模式: {config_summary['select_mode']}\n"
            message += f"📤 发送模式: {config_summary['send_mode']}\n"
            message += f"⏱️ 超时时间: {config_summary['timeout']}秒\n\n"
            
            # 功能配置
            message += f"💬 评论功能: {'✅ 启用' if config_summary['enable_comments'] else '❌ 禁用'}\n"
            message += f"📝 歌词功能: {'✅ 启用' if config_summary['enable_lyrics'] else '❌ 禁用'}\n"
            message += f"🎤 语音模式: {'✅ 启用' if config_summary['enable_record_mode'] else '❌ 禁用'}\n\n"
            
            # 缓存配置
            cache_size_mb = cache_info['total_size'] / (1024 * 1024)
            message += f"💾 缓存状态: {'✅ 启用' if config_summary['cache_enabled'] else '❌ 禁用'}\n"
            message += f"📁 缓存文件: {cache_info['total_files']} 个 (MP3: {cache_info['mp3_files']}, WAV: {cache_info['wav_files']})\n"
            message += f"📊 缓存大小: {cache_size_mb:.2f}MB / {config_summary['cache_max_size']}MB\n"
            message += f"⏰ 保存时间: {config_summary['cache_max_age']}天\n\n"
            
            # 音源支持信息
            message += "🎶 支持音源:\n"
            message += "  • 网易云音乐 (netease)\n"
            message += "  • QQ音乐 (qq)\n"
            message += "  • 酷狗音乐 (kugou)\n"
            message += "  • 网易云NodeJS版 (netease_nodejs)\n\n"
            
            message += "💡 使用提示:\n"
            message += "  • 点歌时可在关键词前加音源类型，如 'qq 周杰伦'\n"
            message += "  • 配置修改后需要重启插件生效\n"
            
            yield event.plain_result(message)
            
        except Exception as e:
            logger.error(f"显示配置信息时出错: {e}")
            yield event.plain_result("获取配置信息时发生错误，请稍后重试~")
    
    @filter.command("清理缓存")
    async def clear_cache(self, event: AstrMessageEvent):
        """清理音乐缓存文件"""
        try:
            # 获取清理前的缓存信息
            cache_info_before = await self.get_cache_info()
            
            # 执行缓存清理
            result = await self.cleanup_cache()
            
            # 获取清理后的缓存信息
            cache_info_after = await self.get_cache_info()
            
            message = "🧹 缓存清理完成\n\n"
            message += f"🗑️ 删除文件: {result['deleted_files']} 个\n"
            message += f"📊 释放空间: {(result['total_size_before'] - result['total_size_after']) / (1024 * 1024):.2f}MB\n"
            message += f"📁 剩余文件: {cache_info_after['total_files']} 个\n"
            message += f"💾 当前大小: {cache_info_after['total_size'] / (1024 * 1024):.2f}MB\n\n"
            
            if result['deleted_files'] == 0:
                message += "💡 提示: 没有需要清理的缓存文件"
            
            yield event.plain_result(message)
            
        except Exception as e:
            logger.error(f"清理缓存时出错: {e}")
            yield event.plain_result("清理缓存时发生错误，请稍后重试~")
    
    def _get_source_name(self, source_type: str) -> str:
        """获取音源名称"""
        source_names = {
            "netease": "网易云音乐",
            "qq": "QQ音乐",
            "kugou": "酷狗音乐"
        }
        return source_names.get(source_type, "未知音源")
    
    async def _fetch_qq_music(self, keyword: str) -> list:
        """搜索QQ音乐"""
        start_time = time.time()
        logger.info(f"[QQ音乐搜索开始] 关键词: {keyword}")
        
        try:
            # QQ音乐API接口
            url = f"http://datukuai.top:1450/djs/API/QQ_Music/api.php?msg={keyword}&n=10"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and isinstance(data, list):
                            songs = []
                            for item in data:
                                songs.append({
                                    "name": item.get("song", "未知歌曲"),
                                    "artists": item.get("singers", "未知歌手"),
                                    "album": item.get("album", "未知专辑"),
                                    "pic_url": item.get("picture", ""),
                                    "url": item.get("music", ""),
                                    "id": item.get("songid", ""),
                                    "duration": item.get("duration", 0),
                                    "source": "qq"
                                })
                            execution_time = time.time() - start_time
                            logger.info(f"[QQ音乐搜索成功] 耗时: {execution_time:.2f}秒, 关键词: {keyword}, 结果数: {len(songs)}")
                            return songs
                    else:
                        execution_time = time.time() - start_time
                        logger.error(f"[QQ音乐搜索失败] 耗时: {execution_time:.2f}秒, 关键词: {keyword}, 状态码: {response.status}")
            return []
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[QQ音乐搜索异常] 耗时: {execution_time:.2f}秒, 关键词: {keyword}, 错误: {e}")
            return []
    
    async def _fetch_kugou_music(self, keyword: str) -> list:
        """搜索酷狗音乐"""
        start_time = time.time()
        logger.info(f"[酷狗音乐搜索开始] 关键词: {keyword}")
        
        try:
            # 酷狗音乐API接口
            url = f"http://mobilecdn.kugou.com/api/v3/search/song?format=json&keyword={keyword}&page=1&pagesize=10&showtype=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and data.get("data"):
                            songs = []
                            for item in data["data"]["info"]:
                                songs.append({
                                    "name": item.get("songname", "未知歌曲"),
                                    "artists": item.get("singername", "未知歌手"),
                                    "album": item.get("album_name", "未知专辑"),
                                    "pic_url": item.get("imgurl", "").replace("{size}", "400"),
                                    "url": f"https://www.kugou.com/song/#hash={item.get('hash', '')}",
                                    "id": item.get("hash", ""),
                                    "duration": item.get("duration", 0),
                                    "source": "kugou"
                                })
                            execution_time = time.time() - start_time
                            logger.info(f"[酷狗音乐搜索成功] 耗时: {execution_time:.2f}秒, 关键词: {keyword}, 结果数: {len(songs)}")
                            return songs
                    else:
                        execution_time = time.time() - start_time
                        logger.error(f"[酷狗音乐搜索失败] 耗时: {execution_time:.2f}秒, 关键词: {keyword}, 状态码: {response.status}")
            return []
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[酷狗音乐搜索异常] 耗时: {execution_time:.2f}秒, 关键词: {keyword}, 错误: {e}")
            return []

    @filter.command("缓存管理")
    async def cache_management(self, event: AstrMessageEvent):
        """缓存管理命令"""
        args = event.message_str.replace("缓存管理", "").strip().split()
        
        if not args:
            # 显示缓存信息
            cache_info = await self.get_cache_info()
            total_size_mb = cache_info["total_size"] / (1024 * 1024)
            
            # 获取缓存目录信息
            cache_dir_info = ""
            if os.path.exists(self.cache_dir):
                cache_dir_info = f"📁 缓存目录: {self.cache_dir}\n"
            
            # 计算使用率
            usage_percent = (total_size_mb / self.cache_max_size) * 100 if self.cache_max_size > 0 else 0
            usage_bar = self._get_usage_bar(usage_percent)
            
            message = (
                f"🎵 音乐缓存信息\n"
                f"{cache_dir_info}"
                f"📊 总文件数: {cache_info['total_files']} 个\n"
                f"💾 总大小: {total_size_mb:.2f} MB\n"
                f"🎶 MP3文件: {cache_info['mp3_files']} 个\n"
                f"🔊 WAV文件: {cache_info['wav_files']} 个\n"
                f"📈 使用率: {usage_percent:.1f}% {usage_bar}\n"
                f"⚙️ 缓存状态: {'✅ 启用' if self.cache_enabled else '❌ 禁用'}\n"
                f"📏 最大大小: {self.cache_max_size} MB\n"
                f"⏰ 最长保存: {self.cache_max_age} 天\n\n"
                f"使用命令:\n"
                f"• 缓存管理 清理 - 清理过期缓存\n"
                f"• 缓存管理 状态 - 查看缓存状态\n"
                f"• 缓存管理 详情 - 查看详细缓存信息\n"
                f"• 缓存管理 启用 - 启用缓存\n"
                f"• 缓存管理 禁用 - 禁用缓存\n"
                f"• 缓存管理 强制清理 - 强制清理所有缓存"
            )
            await event.send(event.plain_result(message))
            return
        
        command = args[0].lower()
        
        if command == "清理" or command == "clean":
            result = await self.cleanup_cache()
            cache_info = await self.get_cache_info()
            total_size_mb = cache_info["total_size"] / (1024 * 1024)
            
            message = (
                f"🧹 缓存清理完成！\n"
                f"🗑️ 删除文件: {result['deleted_files']} 个\n"
                f"📊 剩余文件: {result['remaining_files']} 个\n"
                f"💾 当前大小: {total_size_mb:.2f} MB"
            )
            await event.send(event.plain_result(message))
            
        elif command == "强制清理" or command == "force_clean":
            # 强制清理所有缓存文件
            deleted_count = 0
            if os.path.exists(self.cache_dir):
                for filename in os.listdir(self.cache_dir):
                    filepath = os.path.join(self.cache_dir, filename)
                    if os.path.isfile(filepath) and filename.endswith(('.mp3', '.wav')):
                        try:
                            os.remove(filepath)
                            deleted_count += 1
                            logger.info(f"强制删除缓存文件: {filename}")
                        except Exception as e:
                            logger.warning(f"强制删除缓存文件失败 {filename}: {e}")
            
            message = f"💥 强制清理完成！\n🗑️ 删除文件: {deleted_count} 个"
            await event.send(event.plain_result(message))
            
        elif command == "状态" or command == "status":
            cache_info = await self.get_cache_info()
            total_size_mb = cache_info["total_size"] / (1024 * 1024)
            
            message = (
                f"📊 缓存状态\n"
                f"文件数: {cache_info['total_files']} 个\n"
                f"大小: {total_size_mb:.2f} MB\n"
                f"状态: {'✅ 启用' if self.cache_enabled else '❌ 禁用'}"
            )
            await event.send(event.plain_result(message))
            
        elif command == "详情" or command == "detail":
            # 显示详细的缓存文件信息
            if not os.path.exists(self.cache_dir):
                await event.send(event.plain_result("📁 缓存目录不存在"))
                return
                
            import time
            current_time = time.time()
            
            files_info = []
            total_size = 0
            
            for filename in os.listdir(self.cache_dir):
                filepath = os.path.join(self.cache_dir, filename)
                if os.path.isfile(filepath) and filename.endswith(('.mp3', '.wav')):
                    file_stat = os.stat(filepath)
                    file_size = file_stat.st_size
                    file_age = current_time - file_stat.st_mtime
                    file_age_days = file_age / (24 * 60 * 60)
                    
                    files_info.append({
                        'name': filename,
                        'size': file_size,
                        'age_days': file_age_days
                    })
                    total_size += file_size
            
            # 按文件大小排序
            files_info.sort(key=lambda x: x['size'], reverse=True)
            
            # 显示前10个最大的文件
            message_lines = [f"📋 缓存文件详情 (显示前10个最大文件):\n"]
            for i, file_info in enumerate(files_info[:10]):
                size_mb = file_info['size'] / (1024 * 1024)
                message_lines.append(f"{i+1}. {file_info['name']} - {size_mb:.2f}MB - {file_info['age_days']:.1f}天前")
            
            if len(files_info) > 10:
                message_lines.append(f"... 还有 {len(files_info) - 10} 个文件")
            
            message_lines.append(f"\n📊 总计: {len(files_info)} 个文件, {total_size / (1024 * 1024):.2f} MB")
            
            await event.send(event.plain_result("\n".join(message_lines)))
            
        elif command == "启用" or command == "enable":
            self.cache_enabled = True
            message = "✅ 音乐缓存已启用"
            await event.send(event.plain_result(message))
            
        elif command == "禁用" or command == "disable":
            self.cache_enabled = False
            # 禁用缓存时清理所有缓存文件
            result = await self.cleanup_cache()
            message = f"❌ 音乐缓存已禁用，并清理了 {result['deleted_files']} 个缓存文件"
            await event.send(event.plain_result(message))
            
        else:
            message = "❓ 未知命令，请使用: 清理/状态/详情/启用/禁用/强制清理"
            await event.send(event.plain_result(message))
    
    def _get_usage_bar(self, percent: float) -> str:
        """生成使用率进度条"""
        bar_length = 10
        filled_length = int(round(bar_length * percent / 100))
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        return f"[{bar}]" if percent <= 100 else "[超限]"
    
    async def get_cache_statistics(self) -> dict:
        """获取缓存统计信息"""
        if not os.path.exists(self.cache_dir):
            return {
                "total_files": 0,
                "total_size": 0,
                "mp3_files": 0,
                "wav_files": 0,
                "oldest_file_age": 0,
                "newest_file_age": 0,
                "average_file_size": 0
            }
        
        import time
        current_time = time.time()
        
        total_size = 0
        mp3_count = 0
        wav_count = 0
        file_ages = []
        
        for filename in os.listdir(self.cache_dir):
            filepath = os.path.join(self.cache_dir, filename)
            if os.path.isfile(filepath):
                if filename.endswith('.mp3'):
                    mp3_count += 1
                elif filename.endswith('.wav'):
                    wav_count += 1
                
                file_stat = os.stat(filepath)
                file_size = file_stat.st_size
                file_age = current_time - file_stat.st_mtime
                
                total_size += file_size
                file_ages.append(file_age)
        
        total_files = mp3_count + wav_count
        
        return {
            "total_files": total_files,
            "total_size": total_size,
            "mp3_files": mp3_count,
            "wav_files": wav_count,
            "oldest_file_age": max(file_ages) if file_ages else 0,
            "newest_file_age": min(file_ages) if file_ages else 0,
            "average_file_size": total_size / total_files if total_files > 0 else 0
        }

    async def _send_selection(self, event: AstrMessageEvent, songs: list, source_type: str = "netease") -> None:
        """
        发送歌曲选择
        """
        source_name = self._get_source_name(source_type)
        
        if self.select_mode == "image":
            formatted_songs = [
                f"{index + 1}. {song['name']} - {song['artists']}"
                for index, song in enumerate(songs)
            ]
            image = await self.text_to_image("\n".join(formatted_songs))
            await event.send(MessageChain(chain=[Comp.Image.fromURL(image)]))

        else:
            message_lines = [f"🎵 在{source_name}找到 {len(songs)} 首相关歌曲，请选择序号：\n"]
            
            for i, song in enumerate(songs[:10], 1):
                artist = song.get("artists", song.get("artist", "未知歌手"))
                album = song.get("album", "未知专辑")
                duration = song.get("duration", 0)
                
                # 格式化时长
                duration_str = ""
                if duration > 0:
                    minutes = duration // 60
                    seconds = duration % 60
                    duration_str = f" ({minutes}:{seconds:02d})"
                
                message_lines.append(f"{i}. {song['name']} - {artist}{duration_str}")
            
            message_lines.append("\n请回复序号选择歌曲（60秒内有效）")
            
            await event.send(event.plain_result("\n".join(message_lines)))

    async def _send_song(self, event: AstrMessageEvent, song: dict, source_type: str = "netease"):
        """发送歌曲、热评、歌词"""
        start_time = time.time()
        
        try:
            logger.info(f"[发送歌曲开始] 用户: {event.get_sender_id()}, 歌曲: {song.get('name', '未知')}, 音源: {source_type}")
            
            platform_name = event.get_platform_name()
            send_mode = self.send_mode
            # 发卡片
            if platform_name == "aiocqhttp" and send_mode == "card":
                assert isinstance(event, AiocqhttpMessageEvent)
                client = event.bot
                is_private  = event.is_private_chat()
                
                # 根据音源类型设置卡片类型
                music_type = "163"  # 默认网易云
                if source_type == "qq":
                    music_type = "qq"
                elif source_type == "kugou":
                    music_type = "custom"
                
                payloads: dict = {
                    "message": [
                        {
                            "type": "music",
                            "data": {
                                "type": music_type,
                                "id": str(song["id"]),
                            },
                        }
                    ],
                }
                if is_private:
                    payloads["user_id"] = event.get_sender_id()
                    await client.api.call_action("send_private_msg", **payloads)
                else:
                    payloads["group_id"] = event.get_group_id()
                    await client.api.call_action("send_group_msg", **payloads)

            # record模式 - 发送语音
            elif send_mode == "record":
                if not self.enable_record_mode:
                    logger.warning("record模式未启用")
                    return
                
                # 根据音源类型获取音频URL
                audio_url = ""
                if source_type == "netease":
                    # 网易云音乐
                    extra_data = await self.api.fetch_extra(song_id=song["id"])
                    audio_url = extra_data.get("audio_url", "")
                elif source_type == "qq":
                    # QQ音乐 - 使用歌曲数据中的url字段
                    audio_url = song.get("url", "")
                elif source_type == "kugou":
                    # 酷狗音乐 - 使用歌曲数据中的url字段
                    audio_url = song.get("url", "")
                
                if not audio_url:
                    logger.warning(f"{self._get_source_name(source_type)}歌曲没有音频链接，降级为文字模式")
                    # 降级为文字模式
                    message = f"🎵 {song['name']} - {song['artists']}\n"
                    if song.get("album"):
                        message += f"💿 专辑: {song['album']}\n"
                    message += f"⏱️ 时长: {format_time(song.get('duration', 0))}\n"
                    message += f"🔗 试听链接: {song.get('url', '')}"
                    
                    try:
                        await event.send(event.plain_result(message))
                    except Exception as e:
                        logger.error(f"发送消息失败: {e}")
                    return
                
                # 检测平台类型
                platform_name = str(event.platform).lower() if hasattr(event, 'platform') else ""
                is_telegram = "telegram" in platform_name
                
                try:
                    # 构建富媒体消息链
                    message_chain = []
                    
                    # 歌曲信息
                    message_chain.append(Comp.Plain(f"🎵 {song['name']} - {song['artists']}\n"))
                    
                    # 专辑封面（如果有）
                    if extra_data.get("pic_url"):
                        try:
                            message_chain.append(Comp.Image.fromURL(extra_data["pic_url"]))
                        except Exception as e:
                            logger.warning(f"添加专辑封面失败: {e}")
                    
                    # 音频下载和转换
                    song_id = song.get("id", "unknown")
                    cache_filename = self.get_cache_filename(song_id, audio_url)
                    wav_filename = self.get_wav_cache_filename(song_id, audio_url)
                    wav_path = os.path.join(self.cache_dir, wav_filename)
                    
                    # 检查是否已有wav文件
                    if not os.path.exists(wav_path):
                        # 使用智能缓存查找，尝试查找相同歌曲的缓存文件
                        cached_file = await self.download_audio(audio_url, cache_filename)
                        
                        # 如果智能缓存查找返回的是wav文件路径，直接使用
                        if cached_file and cached_file.endswith('.wav') and os.path.exists(cached_file):
                            wav_path = cached_file
                            logger.info(f"智能缓存查找找到wav文件，直接使用: {os.path.basename(wav_path)}")
                        # 如果返回的是mp3文件路径，需要转换为wav
                        elif cached_file and cached_file.endswith('.mp3') and os.path.exists(cached_file):
                            mp3_path = cached_file
                            # 转换为wav格式
                            if await self.convert_audio_to_wav(mp3_path, wav_path):
                                # 转换成功后删除临时mp3文件（如果缓存已存在则保留）
                                try:
                                    os.remove(mp3_path)
                                except:
                                    pass
                            else:
                                # 转换失败，使用原始mp3路径
                                wav_path = mp3_path
                        else:
                            # 下载失败或缓存未启用，使用在线URL
                            wav_path = audio_url
                    
                    # 语音消息 - 针对Telegram平台优化
                    if is_telegram:
                        # Telegram平台：使用文件发送代替语音消息
                        if os.path.exists(wav_path):
                            # 检查文件大小，Telegram对文件大小有限制
                            file_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
                            if file_size > 50 * 1024 * 1024:  # 50MB限制
                                logger.warning(f"音频文件过大({file_size}字节)，降级为在线URL")
                                message_chain.append(Comp.Record(url=audio_url))
                            else:
                                # 使用文件发送，文件名包含歌曲信息
                                filename = f"{song['name']} - {song['artists']}.wav"
                                message_chain.append(Comp.File(file=wav_path, name=filename))
                                logger.info("Telegram平台：使用文件发送音频")
                        elif audio_url and audio_url.startswith(("http://", "https://")):
                            # 如果没有本地文件，使用在线URL
                            message_chain.append(Comp.Record(url=audio_url))
                            logger.info("Telegram平台：使用在线音频URL发送语音")
                        else:
                            message_chain.append(Comp.Record(url=audio_url))
                    else:
                        # 其他平台：保持原有逻辑
                        if os.path.exists(wav_path):
                            message_chain.append(Comp.Record(file=wav_path, url=wav_path))
                        else:
                            message_chain.append(Comp.Record(url=audio_url))
                    
                    # 音频链接和操作提示
                    message_chain.append(Comp.Plain(f"\n🔗 音频链接: {audio_url}\n"))
                    # 移除平台优化提示，保持简洁
                    
                    await event.send(event.chain_result(message_chain))
                    
                    # 根据缓存配置决定是否删除本地音频文件
                    if not self.cache_enabled:
                        files_to_delete = []
                        if os.path.exists(wav_path) and wav_path.startswith(self.cache_dir):
                            files_to_delete.append(wav_path)
                        
                        # 如果存在原始MP3文件，也加入删除列表
                        mp3_path = os.path.join(self.cache_dir, cache_filename)
                        if os.path.exists(mp3_path):
                            files_to_delete.append(mp3_path)
                        
                        # 删除所有音频文件
                        for file_path in files_to_delete:
                            try:
                                os.remove(file_path)
                                logger.info(f"语音发送成功，已删除本地音频文件: {file_path}")
                            except Exception as e:
                                logger.warning(f"删除本地音频文件失败 {file_path}: {e}")
                    else:
                        # 缓存启用时，更新文件修改时间以延长缓存寿命
                        import time
                        if os.path.exists(wav_path) and wav_path.startswith(self.cache_dir):
                            try:
                                os.utime(wav_path, (time.time(), time.time()))
                                logger.info(f"语音发送成功，缓存文件已更新: {wav_path}")
                            except Exception as e:
                                logger.warning(f"更新缓存文件时间失败 {wav_path}: {e}")
                    
                except Exception as e:
                    logger.error(f"发送语音消息失败: {e}")
                    
                    # 针对Telegram平台的特定错误处理
                    if is_telegram:
                        error_msg = str(e).lower()
                        if "server disconnected" in error_msg or "disconnected" in error_msg or "file" in error_msg:
                            logger.warning("Telegram平台文件发送失败，尝试降级为在线语音模式")
                            try:
                                # 尝试只发送在线语音，不包含其他富媒体内容
                                simple_chain = [Comp.Record(url=audio_url)]
                                await event.send(event.chain_result(simple_chain))
                                logger.info("Telegram在线语音发送成功")
                                return
                            except Exception as simple_error:
                                logger.error(f"Telegram在线语音发送也失败: {simple_error}")
                    
                    # 降级为富媒体文字模式
                    try:
                        fallback_chain = [
                            Comp.Plain(f"🎵 {song['name']} - {song['artists']}\n"),
                            Comp.Plain(f"💿 专辑: {song.get('album', '未知')}\n"),
                            Comp.Plain(f"⏱️ 时长: {format_time(song.get('duration', 0))}\n"),
                            Comp.Plain(f"🔗 试听链接: {song.get('url', '')}\n"),
                            Comp.Plain(f"🎧 音频链接: {audio_url}\n"),
                            Comp.Plain("⚠️ 语音发送失败，已降级为文字模式")
                        ]
                        await event.send(event.chain_result(fallback_chain))
                    except Exception as fallback_error:
                        logger.error(f"降级发送也失败: {fallback_error}")

            # 合并模式
            elif send_mode == "forward":
                # 根据音源类型获取音频URL
                audio_url = ""
                if source_type == "netease":
                    # 网易云音乐
                    extra_data = await self.api.fetch_extra(song_id=song["id"])
                    audio_url = extra_data.get("audio_url", "")
                elif source_type == "qq":
                    # QQ音乐 - 使用歌曲数据中的url字段
                    audio_url = song.get("url", "")
                elif source_type == "kugou":
                    # 酷狗音乐 - 使用歌曲数据中的url字段
                    audio_url = song.get("url", "")
                
                # 构建合并消息内容
                message_parts = []
                
                # 歌曲信息
                song_info = (
                    f"🎶 歌曲信息\n"
                    f"歌曲：{song.get('name')}\n"
                    f"歌手：{song.get('artists')}\n"
                    f"时长：{format_time(song['duration'])}\n"
                    f"链接：{audio_url if audio_url else '暂无音频链接'}\n"
                )
                message_parts.append(song_info)
                
                # 评论（如果启用，仅支持网易云音乐）
                if self.enable_comments and source_type == "netease":
                    try:
                        comments = await self.api.fetch_comments(song_id=song["id"])
                        if comments:
                            content = random.choice(comments)["content"]
                            comment_text = f"💬 热门评论\n{content}\n"
                            message_parts.append(comment_text)
                    except Exception as e:
                        logger.warning(f"获取评论失败: {str(e)}")
                
                # 歌词（如果启用，仅支持网易云音乐）
                if self.enable_lyrics and source_type == "netease":
                    try:
                        lyrics = await self.api.fetch_lyrics(song_id=song["id"])
                        if lyrics and lyrics != "歌词未找到":
                            # 只显示前10行歌词
                            lyrics_lines = lyrics.split('\n')[:10]
                            lyrics_preview = '\n'.join(lyrics_lines)
                            lyrics_text = f"📝 歌词预览\n{lyrics_preview}\n"
                            message_parts.append(lyrics_text)
                    except Exception as e:
                        logger.warning(f"获取歌词失败: {str(e)}")
                
                # 合并所有部分并发送
                combined_message = "\n".join(message_parts)
                await event.send(event.plain_result(combined_message))

            # 发文字
            else:
                # 根据音源类型获取音频URL
                audio_url = ""
                if source_type == "netease":
                    # 网易云音乐
                    extra_data = await self.api.fetch_extra(song_id=song["id"])
                    audio_url = extra_data.get("audio_url", "")
                elif source_type == "qq":
                    # QQ音乐 - 使用歌曲数据中的url字段
                    audio_url = song.get("url", "")
                elif source_type == "kugou":
                    # 酷狗音乐 - 使用歌曲数据中的url字段
                    audio_url = song.get("url", "")
                
                song_info_str = (
                    f"🎶{song.get('name')} - {song.get('artists')} {format_time(song['duration'])}\n"
                    f"🔗链接：{audio_url if audio_url else '暂无音频链接'}"
                )
                await event.send(event.plain_result(song_info_str))

            # 发送评论（仅支持网易云音乐）
            if self.enable_comments and source_type == "netease":
                try:
                    comments = await self.api.fetch_comments(song_id=song["id"])
                    if comments:
                        content = random.choice(comments)["content"]
                        await event.send(event.plain_result(content))
                    else:
                        logger.debug(f"歌曲 {song['id']} 没有评论")
                except Exception as e:
                    logger.warning(f"获取评论失败: {str(e)}")

            # 发送歌词（仅支持网易云音乐）
            if self.enable_lyrics and source_type == "netease":
                try:
                    lyrics = await self.api.fetch_lyrics(song_id=song["id"])
                    if lyrics and lyrics != "歌词未找到":
                        image = draw_lyrics(lyrics)
                        await event.send(MessageChain(chain=[Comp.Image.fromBytes(image)]))
                    else:
                        logger.debug(f"歌曲 {song['id']} 没有歌词")
                except Exception as e:
                    logger.warning(f"获取歌词失败: {str(e)}")

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[发送歌曲失败] 用户: {event.get_sender_id()}, 歌曲: {song.get('name', '未知')}, 耗时: {execution_time:.2f}秒, 错误: {str(e)}")
            
            # 检查是否是Telegram平台且错误与语音相关
            platform_name = str(event.platform).lower() if hasattr(event, 'platform') else ""
            error_msg = str(e).lower()
            
            # 如果是Telegram平台且出现服务器断开连接错误，降级为文字模式
            if "telegram" in platform_name and ("server disconnected" in error_msg or "disconnected" in error_msg):
                logger.warning("Telegram平台语音发送失败，降级为文字模式")
                try:
                    # 根据音源类型获取音频URL
                    audio_url = ""
                    if source_type == "netease":
                        # 网易云音乐
                        extra_data = await self.api.fetch_extra(song_id=song["id"])
                        audio_url = extra_data.get("audio_url", "")
                    elif source_type == "qq":
                        # QQ音乐 - 使用歌曲数据中的url字段
                        audio_url = song.get("url", "")
                    elif source_type == "kugou":
                        # 酷狗音乐 - 使用歌曲数据中的url字段
                        audio_url = song.get("url", "")
                    
                    # 构建降级后的文字消息
                    fallback_message = (
                        f"🎵 {song['name']} - {song['artists']}\n"
                        f"💿 专辑: {song.get('album', '未知')}\n"
                        f"⏱️ 时长: {format_time(song.get('duration', 0))}\n"
                        f"🔗 试听链接: {song.get('url', '')}\n"
                        f"🎧 音频链接: {audio_url if audio_url else '暂无'}\n"
                        f"⚠️ Telegram平台语音发送受限，已自动降级为文字模式"
                    )
                    await event.send(event.plain_result(fallback_message))
                    
                    # 记录降级发送成功
                    logger.info(f"[发送歌曲降级成功] 用户: {event.get_sender_id()}, 歌曲: {song.get('name', '未知')}, 耗时: {execution_time:.2f}秒")
                    return
                except Exception as fallback_error:
                    logger.error(f"[发送歌曲降级失败] 用户: {event.get_sender_id()}, 歌曲: {song.get('name', '未知')}, 耗时: {execution_time:.2f}秒, 错误: {fallback_error}")
            
            # 发送基本的错误信息
            error_msg = f"发送歌曲信息时出现错误，请稍后重试"
            await event.send(event.plain_result(error_msg))
        else:
            # 发送成功，记录执行时间
            execution_time = time.time() - start_time
            logger.info(f"[发送歌曲完成] 用户: {event.get_sender_id()}, 歌曲: {song.get('name', '未知')}, 音源: {source_type}, 耗时: {execution_time:.2f}秒")




