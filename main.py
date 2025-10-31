
import random
import traceback
import os
import asyncio
import aiofiles
import aiohttp
import hashlib
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

        # 默认API
        self.default_api = config.get("default_api", "netease")
        # 网易云nodejs服务的默认端口
        self.nodejs_base_url = config.get(
            "nodejs_base_url", "http://netease_cloud_music_api:3000"
        )
        if self.default_api == "netease":
            from .api import NetEaseMusicAPI

            self.api = NetEaseMusicAPI()

        elif self.default_api == "netease_nodejs":
            from .api import NetEaseMusicAPINodeJs
            self.api = NetEaseMusicAPINodeJs(base_url=self.nodejs_base_url)
        
        # 音频缓存目录
        self.cache_dir = "data/plugins/astrbot_plugin_music/cache"
        os.makedirs(self.cache_dir, exist_ok=True)
        
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
        # elif self.default_api == "tencent":
        #     from .api import TencentMusicAPI
        #     self.api = TencentMusicAPI()
    
    async def download_audio(self, url: str, filename: str) -> str:
        """下载音频文件到本地缓存"""
        filepath = os.path.join(self.cache_dir, filename)
        
        # 如果文件已存在，直接返回路径
        if os.path.exists(filepath):
            return filepath
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        async with aiofiles.open(filepath, 'wb') as f:
                            await f.write(await response.read())
                        logger.info(f"音频文件已下载: {filepath}")
                        return filepath
                    else:
                        logger.error(f"下载音频失败，状态码: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"下载音频时出错: {e}")
            return None
    
    def get_cache_filename(self, song_id: str, audio_url: str) -> str:
        """生成缓存文件名"""
        # 使用歌曲ID和音频URL的哈希值作为文件名
        url_hash = hashlib.md5(audio_url.encode()).hexdigest()[:8]
        return f"{song_id}_{url_hash}.mp3"
    
    async def convert_audio_to_wav(self, input_path: str, output_path: str) -> bool:
        """将音频转换为wav格式（需要安装ffmpeg）"""
        try:
            import subprocess
            result = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', input_path, '-acodec', 'pcm_s16le', 
                '-ar', '16000', '-ac', '1', output_path,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                logger.info(f"音频转换成功: {output_path}")
                return True
            else:
                logger.error(f"音频转换失败: {stderr.decode()}")
                return False
        except Exception as e:
            logger.error(f"音频转换时出错: {e}")
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
        """搜索歌曲供用户选择"""
        args = event.message_str.replace("点歌", "").split()
        if not args:
            yield event.plain_result("没给歌名喵~")
            return

        # 解析序号和歌名
        index: int = int(args[-1]) if args[-1].isdigit() else 0
        song_name = " ".join(args[:-1]) if args[-1].isdigit() else " ".join(args)

        # 搜索歌曲
        songs = await self.api.fetch_data(keyword=song_name)
        if not songs:
            yield event.plain_result("没能找到这首歌喵~")
            return

        # 输入了序号，直接发送歌曲
        if index and 0 <= index <= len(songs):
            selected_song = songs[int(index) - 1]
            await self._send_song(event, selected_song)

        # 未提输入序号，等待用户选择歌曲
        else:
            await self._send_selection(event=event, songs=songs)

            @session_waiter(timeout=self.timeout, record_history_chains=False)  # type: ignore  # noqa: F821
            async def empty_mention_waiter(
                controller: SessionController, event: AstrMessageEvent
            ):
                index = event.message_str
                if not index.isdigit() or int(index) < 1 or int(index) > len(songs):
                    return
                selected_song = songs[int(index) - 1]
                await self._send_song(event=event, song=selected_song)
                controller.stop()

            try:
                await empty_mention_waiter(event)  # type: ignore
            except TimeoutError as _:
                yield event.plain_result("点歌超时！")
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error("点歌发生错误" + str(e))

        event.stop_event()

    async def _send_selection(self, event: AstrMessageEvent, songs: list) -> None:
        """
        发送歌曲选择
        """
        if self.select_mode == "image":
            formatted_songs = [
                f"{index + 1}. {song['name']} - {song['artists']}"
                for index, song in enumerate(songs)
            ]
            image = await self.text_to_image("\n".join(formatted_songs))
            await event.send(MessageChain(chain=[Comp.Image.fromURL(image)]))

        else:
            formatted_songs = [
                f"{index + 1}. {song['name']} - {song['artists']}"
                for index, song in enumerate(songs)
            ]
            await event.send(event.plain_result("\n".join(formatted_songs)))

    async def _send_song(self, event: AstrMessageEvent, song: dict):
        """发送歌曲、热评、歌词"""

        platform_name = event.get_platform_name()
        send_mode = self.send_mode

        try:
            # 发卡片
            if platform_name == "aiocqhttp" and send_mode == "card":
                assert isinstance(event, AiocqhttpMessageEvent)
                client = event.bot
                is_private  = event.is_private_chat()
                payloads: dict = {
                    "message": [
                        {
                            "type": "music",
                            "data": {
                                "type": "163",
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
                
                extra_data = await self.api.fetch_extra(song_id=song["id"])
                audio_url = extra_data.get("audio_url", "")
                if not audio_url:
                    logger.warning("歌曲没有音频链接，降级为文字模式")
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
                    wav_filename = cache_filename.replace(".mp3", ".wav")
                    wav_path = os.path.join(self.cache_dir, wav_filename)
                    
                    # 检查是否已有wav文件
                    if not os.path.exists(wav_path):
                        # 下载音频文件
                        mp3_path = await self.download_audio(audio_url, cache_filename)
                        if mp3_path:
                            # 转换为wav格式
                            if await self.convert_audio_to_wav(mp3_path, wav_path):
                                # 转换成功后删除临时mp3文件
                                try:
                                    os.remove(mp3_path)
                                except:
                                    pass
                            else:
                                # 转换失败，使用原始mp3路径
                                wav_path = mp3_path
                        else:
                            # 下载失败，使用在线URL
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
                    
                    # 发送成功后删除本地音频文件
                    files_to_delete = []
                    if os.path.exists(wav_path):
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
                # 获取歌曲信息
                extra_data = await self.api.fetch_extra(song_id=song["id"])
                audio_url = extra_data.get("audio_url", "")
                
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
                
                # 评论（如果启用）
                if self.enable_comments:
                    try:
                        comments = await self.api.fetch_comments(song_id=song["id"])
                        if comments:
                            content = random.choice(comments)["content"]
                            comment_text = f"💬 热门评论\n{content}\n"
                            message_parts.append(comment_text)
                    except Exception as e:
                        logger.warning(f"获取评论失败: {str(e)}")
                
                # 歌词（如果启用）
                if self.enable_lyrics:
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
                extra_data = await self.api.fetch_extra(song_id=song["id"])
                audio_url = extra_data.get("audio_url", "")
                song_info_str = (
                    f"🎶{song.get('name')} - {song.get('artists')} {format_time(song['duration'])}\n"
                    f"🔗链接：{audio_url if audio_url else '暂无音频链接'}"
                )
                await event.send(event.plain_result(song_info_str))

            # 发送评论
            if self.enable_comments:
                try:
                    comments = await self.api.fetch_comments(song_id=song["id"])
                    if comments:
                        content = random.choice(comments)["content"]
                        await event.send(event.plain_result(content))
                    else:
                        logger.debug(f"歌曲 {song['id']} 没有评论")
                except Exception as e:
                    logger.warning(f"获取评论失败: {str(e)}")

            # 发送歌词
            if self.enable_lyrics:
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
            logger.error(f"发送歌曲信息失败: {str(e)}")
            
            # 检查是否是Telegram平台且错误与语音相关
            platform_name = str(event.platform).lower() if hasattr(event, 'platform') else ""
            error_msg = str(e).lower()
            
            # 如果是Telegram平台且出现服务器断开连接错误，降级为文字模式
            if "telegram" in platform_name and ("server disconnected" in error_msg or "disconnected" in error_msg):
                logger.warning("Telegram平台语音发送失败，降级为文字模式")
                try:
                    # 构建降级后的文字消息
                    extra_data = await self.api.fetch_extra(song_id=song["id"])
                    audio_url = extra_data.get("audio_url", "")
                    fallback_message = (
                        f"🎵 {song['name']} - {song['artists']}\n"
                        f"💿 专辑: {song.get('album', '未知')}\n"
                        f"⏱️ 时长: {format_time(song.get('duration', 0))}\n"
                        f"🔗 试听链接: {song.get('url', '')}\n"
                        f"🎧 音频链接: {audio_url if audio_url else '暂无'}\n"
                        f"⚠️ Telegram平台语音发送受限，已自动降级为文字模式"
                    )
                    await event.send(event.plain_result(fallback_message))
                    return
                except Exception as fallback_error:
                    logger.error(f"降级发送也失败: {fallback_error}")
            
            # 发送基本的错误信息
            error_msg = f"发送歌曲信息时出现错误，请稍后重试"
            await event.send(event.plain_result(error_msg))




