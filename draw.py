import io
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont
import asyncio
import aiohttp
import aiofiles
from io import BytesIO
from bs4 import BeautifulSoup
import hashlib
from astrbot import logger


font_path = Path("data/plugins/astrbot_plugin_music/simhei.ttf")

def draw_lyrics(
    lyrics: str,
    image_width=1000,
    font_size=30,
    line_spacing=20,
    top_color=(255, 250, 240),  # 暖白色
    bottom_color=(235, 255, 247),
    text_color=(70, 70, 70),
) -> bytes:
    """
    渲染歌词为图片，背景为竖向渐变色，返回 JPEG 字节流。
    """
    # 清除时间戳但保留空白行
    lines = lyrics.splitlines()
    cleaned_lines = []
    for line in lines:
        cleaned = re.sub(r"\[\d{2}:\d{2}(?:\.\d{2,3})?\]", "", line)
        cleaned_lines.append(cleaned if cleaned != "" else "")

    # 加载字体
    font = ImageFont.truetype(font_path, font_size)

    # 计算总高度
    dummy_img = Image.new("RGB", (image_width, 1))
    draw = ImageDraw.Draw(dummy_img)
    line_heights = [
        draw.textbbox((0, 0), line if line.strip() else "　", font=font)[3]
        for line in cleaned_lines
    ]
    total_height = int(sum(line_heights) + line_spacing * (len(cleaned_lines) - 1) + 100)

    # 创建渐变背景图像
    img = Image.new("RGB", (image_width, total_height))
    for y in range(total_height):
        ratio = y / total_height
        r = int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio)
        g = int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio)
        b = int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio)
        for x in range(image_width):
            img.putpixel((x, y), (r, g, b))

    draw = ImageDraw.Draw(img)

    # 绘制歌词文本（居中）
    y = 50
    for line, line_height in zip(cleaned_lines, line_heights):
        text = line if line.strip() else "　"  # 全角空格占位
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(((image_width - text_width) / 2, y), text, font=font, fill=text_color)
        y += line_height + line_spacing

    # 输出到字节流
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)
    return img_bytes.getvalue()



class MusicCardRenderer:
    def __init__(
        self,
        font_path: Path,
        cache_dir: Path = Path("image_cache"),
        card_width: int = 380,
        card_height: int = 130,
        margin: int = 20,
        corner_radius: int = 15,
        max_concurrency: int = 10,
    ):
        self.font_path = font_path
        self.cache_dir = cache_dir
        self.card_width = card_width
        self.card_height = card_height
        self.margin = margin
        self.corner_radius = corner_radius
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, url: str) -> Path:
        # 生成唯一文件名
        name = hashlib.md5(url.encode()).hexdigest() + ".jpg"
        return self.cache_dir / name

    async def download_image(
        self, url: str, session: aiohttp.ClientSession
    ) -> Image.Image:
        cache_path = self._get_cache_path(url)
        if cache_path.exists():
            return Image.open(cache_path).convert("RGB")

        async with self.semaphore:
            async with session.get(url) as resp:
                if resp.status == 200:
                    img_bytes = await resp.read()
                    async with aiofiles.open(cache_path, "wb") as f:
                        await f.write(img_bytes)
                    return Image.open(BytesIO(img_bytes)).convert("RGB")
                raise ValueError(f"下载失败: {url}")

    def format_count(self, count: int) -> str:
        if count >= 10000:
            return f"{count / 10000:.1f}万"
        elif count >= 1000:
            return f"{count / 1000:.1f}千"
        return str(count)

    def format_duration(self, duration: int) -> str:
        """
        将毫秒转换为 mm:ss 格式
        """
        total_seconds = int(duration / 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    async def draw_card(
        self,
        video: dict,
        font: ImageFont.FreeTypeFont,
        session: aiohttp.ClientSession,
        index: int,
    ) -> Image.Image:
        try:
            # 创建卡片背景（渐变效果）
            card = Image.new("RGBA", (self.card_width, self.card_height), "#ffffff")
            draw = ImageDraw.Draw(card)
            
            # 绘制渐变背景
            for y in range(self.card_height):
                ratio = y / self.card_height
                r = int(240 * (1 - ratio) + 220 * ratio)
                g = int(245 * (1 - ratio) + 230 * ratio)
                b = int(250 * (1 - ratio) + 240 * ratio)
                draw.line([(0, y), (self.card_width, y)], fill=(r, g, b))
            
            # 绘制卡片边框和阴影效果
            draw.rectangle([0, 0, self.card_width, self.card_height], outline="#e0e0e0", width=1)
            
            # 绘制序号标签
            draw.rounded_rectangle([15, 15, 45, 45], radius=15, fill="#4a90e2")
            # 使用更大的字体绘制序号
            index_font = ImageFont.truetype(self.font_path, 24)
            draw.text((22, 18), str(index), font=index_font, fill="#ffffff")
            
            # 标题（使用更大的字体）
            title = video.get("title", video.get("name", "未知歌曲"))
            # 移除可能的HTML标签
            title = re.sub(r'<[^>]+>', '', title)
            # 处理长标题，限制字数
            if len(title) > 35:
                title = title[:35] + "..."
            # 使用更大的字体大小绘制标题
            title_font = ImageFont.truetype(self.font_path, 26)
            draw.text((65, 20), title, font=title_font, fill="#333333")
            
            # 歌手信息（第二行，使用更大的字体）
            author = video.get("author", video.get("artists", "未知歌手"))
            # 移除可能的HTML标签
            author = re.sub(r'<[^>]+>', '', author)
            # 处理长歌手名
            if len(author) > 25:
                author = author[:25] + "..."
            # 使用更大的字体大小
            info_font = ImageFont.truetype(self.font_path, 22)
            # 第二行显示歌手信息
            draw.text(
                (65, 60),
                f"歌手: {author}",
                font=info_font,
                fill="#666666",
            )
            
            # 时长信息（第三行，使用更大的字体）
            duration = video.get("duration", 0)
            # 第三行显示时长信息
            draw.text(
                (65, 90),
                f"时长: {self.format_duration(duration)}",
                font=info_font,
                fill="#666666",
            )
            
            # 创建圆角遮罩
            mask = Image.new("L", (self.card_width, self.card_height), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.rounded_rectangle(
                (0, 0, self.card_width, self.card_height),
                radius=self.corner_radius,
                fill=255,
            )
            # 应用圆角遮罩
            card.putalpha(mask)
            
            return card
        except Exception as e:
            logger.error(f"[错误] 渲染卡片失败: {e}")
            # 返回空白卡片以避免中断整个流程
            return Image.new("RGBA", (self.card_width, self.card_height), "#ffffff")

    async def render_video_list_image(
        self, video_list: list, cards_per_row: int = 3, quality: int = 85
    ) -> bytes:
        # 使用更大的字体大小，确保与卡片字体协调
        font = ImageFont.truetype(self.font_path, 20)

        async with aiohttp.ClientSession() as session:
            tasks = [
                self.draw_card(video, font, session, index=i + 1)
                for i, video in enumerate(video_list)
            ]
            cards = await asyncio.gather(*tasks)

        # 计算总行数
        total_rows = (len(cards) + cards_per_row - 1) // cards_per_row
        
        # 增加卡片之间的间距，确保布局美观
        card_spacing = 30
        
        # 计算画布尺寸，确保整个画布尺寸合适
        row_width = cards_per_row * self.card_width + (cards_per_row - 1) * card_spacing
        total_width = row_width + 2 * self.margin
        # 增加整个画布的高度，确保有足够的空间
        header_height = 100
        total_height = header_height + total_rows * self.card_height + (total_rows - 1) * card_spacing + 2 * self.margin
        
        # 创建主画布，使用柔和的背景色
        canvas = Image.new(
            "RGBA",
            (total_width, total_height),
            color="#f8f9fa",
        )
        draw = ImageDraw.Draw(canvas)
        
        # 绘制标题（使用更大的字体）
        title_font = ImageFont.truetype(self.font_path, 32)
        title = "歌曲搜索结果"
        bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = bbox[2] - bbox[0]
        draw.text(((total_width - title_width) / 2, 20), title, font=title_font, fill="#333333")
        
        # 绘制说明文字 - 移动到左上角，使用更大的字体
        footer_font = ImageFont.truetype(self.font_path, 18)
        footer_text = "请回复序号选择歌曲，例如：1"
        draw.text((self.margin, 65), footer_text, font=footer_font, fill="#666666")
        
        # 绘制标题下方的分割线
        draw.line([(self.margin, 90), (total_width - self.margin, 90)], fill="#e0e0e0", width=2)
        
        # 拼接所有卡片，增加卡片间距
        y_offset = 110  # 标题、说明文字和分割线占用的高度
        for i in range(0, len(cards), cards_per_row):
            row_cards = cards[i : i + cards_per_row]
            x_offset = self.margin
            for j, card in enumerate(row_cards):
                canvas.paste(card, (x_offset, y_offset), card)
                x_offset += self.card_width + card_spacing
            y_offset += self.card_height + card_spacing

        # 转换为 RGB 并保存
        final_image = Image.new("RGB", canvas.size, "#f8f9fa")
        final_image.paste(canvas, mask=canvas.split()[3])

        buffer = BytesIO()
        final_image.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
