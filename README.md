
<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_music?name=astrbot_plugin_music&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_music

_✨ [astrbot](https://github.com/AstrBotDevs/AstrBot) 点歌插件 ✨_  

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-3.4%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)

</div>

## 🤝 介绍

音乐搜索、热评、语音播放、富媒体消息

## ✨ 新增功能

### 🎵 语音模式增强
- **音频下载缓存**：自动下载音频文件到本地缓存，提高响应速度
- **格式转换优化**：支持MP3到WAV格式自动转换，提高兼容性
- **智能文件管理**：语音发送后自动清理临时文件，节省磁盘空间
- **富媒体消息**：支持歌曲信息、专辑封面、语音消息的完整展示

### 🔄 合并模式
- **消息整合**：将歌曲信息、热门评论、歌词预览合并为一条消息发送
- **跨平台兼容**：支持所有AstrBot平台，无需特殊平台支持
- **智能降级**：评论或歌词获取失败时自动跳过，不影响主功能

### ⚙️ 配置选项增强
- **选择模式**：支持文本模式(text)和图片模式(image)
- **发送模式**：支持卡片模式(card)、语音模式(record)、文本模式(text)、合并模式(forward)
- **功能开关**：可独立控制评论、歌词、语音模式的启用状态

## 📦 安装

- 直接在astrbot的插件市场搜索astrbot_plugin_music，点击安装，等待完成即可

- 也可以克隆源码到插件文件夹：

```bash
# 克隆仓库到插件目录
cd /AstrBot/data/plugins
git clone https://github.com/Zhalslar/astrbot_plugin_music

# 控制台重启AstrBot
```

## ⌨️ 配置

请前往插件配置面板进行配置

## 使用说明

### 基本命令

|     命令      |      说明       |
|:-------------:|:-----------------------------:|
| /点歌 歌名      | 根据序号点歌,可以附加歌手名  |

### 发送模式说明

#### 🎵 语音模式 (record)
- **功能**：发送语音消息，支持本地缓存和格式转换
- **配置**：设置 `send_mode` 为 `record`，并启用 `enable_record_mode`
- **特点**：自动下载音频、转换格式、发送后清理临时文件

#### 🔄 合并模式 (forward)  
- **功能**：将歌曲信息、评论、歌词合并为一条消息发送
- **配置**：设置 `send_mode` 为 `forward`
- **特点**：消息整合、跨平台兼容、智能降级

#### 💳 卡片模式 (card)
- **功能**：发送音乐卡片（仅支持aiocqhttp平台）
- **配置**：设置 `send_mode` 为 `card`

#### 📝 文本模式 (text)
- **功能**：发送纯文本歌曲信息
- **配置**：设置 `send_mode` 为 `text`

### 配置示例

```json
{
  "send_mode": "record",
  "enable_record_mode": true,
  "enable_comments": true,
  "enable_lyrics": false,
  "select_mode": "text"
}
```

## 网易云Nodejs模块说明

> 通过网易云Nodejs项目，使用互联网上公开的项目资源 或 自己部署项目 来获得稳定的网易云音源

>项目地址：[网易云Nodejs项目官网](https://neteasecloudmusicapi.js.org/#/)
- 通过公开的项目获取音源

  如果你不想搭建服务器，又不能使用默认的服务，可以在互联网上搜索`allinurl:eapi_decrypt.html`来寻找公开项目的域名。下面贴一些搜集的公开url。
  ```text
  https://163api.qijieya.cn
  https://zm.armoe.cn
  http://dg-t.cn:3000
  http://111.229.38.178:3333
  https://wyy.xhily.com/
  http://45.152.64.114:3005
  http://42.193.244.179:3000
  https://music-api.focalors.ltd
  ```
  举例：插件的`nodejs_base_url`参数设置为`https://163api.qijieya.cn`，`default_api`调为`netease_nodejs`，即可完成配置。可以多尝试几个域名来寻找稳定音源。
- 部署自己的项目

  通过官网介绍部署项目，获得稳定音源。这里介绍docker compose快速部署。

  修改`astrbot.yml`文件，添加服务
  ```yaml
    netease_cloud_music_api:
      image: binaryify/netease_cloud_music_api
      container_name: netease_cloud_music_api
      environment:
        - http_proxy=
        - https_proxy=
        - no_proxy=
        - HTTP_PROXY=
        - HTTPS_PROXY=
        - NO_PROXY=
      networks:
        - astrbot_network
      # ports:
      #   - "3000:3000" 可以通过公共端口来调试
  ```
  然后在`astrbot.yml`文件所在的目录运行命令启动服务：
  ```cmd
  docker compose -f astrbot.yml up -d netease_cloud_music_api
  ```
  如果你开放了上面的调试端口，可以通过`{主机名}:3000`访问示例页面

  将参数`nodejs_base_url`设置为`http://netease_cloud_music_api:3000`,`default_api`调为`netease_nodejs`，即可完成配置。

  这里的端口号3000可以修改成其他端口，具体见 Nodejs项目 文档。

# TODO

- [ ] 支持多源：网易云音乐、QQ音乐、酷狗音乐...
- [x] 兼容多平台：QQ、Telegram、~~微信（微信已死）~~...（QQ以外的平台需支持发送语音才适配）
- [x] 附加一条热评
- [ ] 支持收藏夹，建立歌单
- [ ] 支持llm智能推送、llm评价
- [ ] 支持自动推送下一首
- [x] ~~QQ平台支持按钮点歌(QQ按钮已死)~~
- [x] 语音模式增强（音频下载缓存、格式转换、富媒体消息）
- [x] 合并模式（消息整合、跨平台兼容）
- [x] 智能文件管理（发送后自动清理临时文件）


## 👥 贡献指南

- 🌟 Star 这个项目！（点右上角的星星，感谢支持！）
- 🐛 提交 Issue 报告问题
- 💡 提出新功能建议
- 🔧 提交 Pull Request 改进代码

## 📌 注意事项

- 想第一时间得到反馈的可以来作者的插件反馈群（QQ群）：460973561（不点star不给进）

## ❤️ Contributors

<a href="https://github.com/Zhalslar/astrbot_plugin_music/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Zhalslar/astrbot_plugin_music" />
</a>
