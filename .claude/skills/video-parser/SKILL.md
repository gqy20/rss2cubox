---
name: video-parser
description: 视频解析工具，用于下载视频、提取字幕、获取元数据。支持 YouTube、Bilibili 等平台。当用户需要"下载视频"、"获取字幕"、"解析视频"、"转录视频"时使用。
allowed-tools: Bash(yt-dlp:*), Bash(ffmpeg:*)
---

# 视频解析工具 (video-parser)

使用 yt-dlp 解析和下载视频内容。

## 前置要求

```bash
# 安装依赖
pip install yt-dlp

# 确保 ffmpeg 已安装
which ffmpeg
```

## 支持的平台

| 平台 | 视频下载 | 字幕提取 | 元数据 | 无需登录 |
|------|---------|---------|--------|---------|
| YouTube | ✅ | ✅ | ✅ | ✅ |
| Bilibili | ✅ | ❌ | ✅ | ✅ |
| 抖音 | ⚠️ | ❌ | ⚠️ | 需要 Cookie |
| 小红书 | ⚠️ | ❌ | ⚠️ | 需要 Cookie |
| TikTok | ⚠️ | ❌ | ⚠️ | 需要代理 |

## 常用命令

### 1. 获取视频元数据

```bash
# 获取视频基本信息 (JSON 格式)
yt-dlp -j "视频URL" | jq '{title, description, uploader, view_count, like_count, duration}'

# 示例
yt-dlp -j "https://www.youtube.com/watch?v=dQw4w9WgXcQ" | jq '{title, view_count}'
```

### 2. 下载字幕/转录

```bash
# 下载所有可用字幕
yt-dlp --write-subs --write-auto-subs --skip-download "视频URL"

# 下载指定语言字幕
yt-dlp --write-subs --write-auto-subs --sub-lang zh-CN --skip-download "视频URL"

# 下载后提取纯文本 (无时间戳)
yt-dlp --write-subs --write-auto-subs --sub-lang en --skip-download "视频URL" -o /tmp/video
# 然后手动处理 .vtt 文件移除时间戳
```

### 3. 下载视频

```bash
# 下载最佳质量视频
yt-dlp "视频URL" -o ~/Downloads/video.mp4

# 下载指定格式 (最高 720p)
yt-dlp -f "best[height<=720]" "视频URL" -o video.mp4

# 下载 B 站视频 (音视频分开，需要合并)
yt-dlp -f "30080+30216" "https://www.bilibili.com/video/BV1xxx" -o video.mp4
```

### 4. 查看可用格式

```bash
# 列出所有可用格式
yt-dlp --list-formats "视频URL"
```

## 常用选项

| 选项 | 说明 |
|------|------|
| `-j` | 输出 JSON 元数据 |
| `--list-formats` | 列出可用格式 |
| `--list-subs` | 列出可用字幕 |
| `-f FORMAT` | 指定下载格式 |
| `-o PATH` | 指定输出路径 |
| `--write-subs` | 下载字幕文件 |
| `--write-auto-subs` | 下载自动生成的字幕 |
| `--skip-download` | 只下载字幕，不下载视频 |

## 格式代码

| 代码 | 说明 |
|------|------|
| `best` | 最佳质量 |
| `bestvideo+bestaudio` | 最佳视频+最佳音频 |
| `best[height<=720]` | 不超过 720p |
| `worst` | 最差质量 |

## 故障排除

### YouTube 需要伪装浏览器
```bash
# 如果遇到错误，安装 impersonate
pip install impersonate
```

### 抖音/小红书需要 Cookie
```bash
# 从浏览器导出 Cookie
yt-dlp --cookies-from-browser chrome "URL"
# 或手动指定 Cookie 文件
yt-dlp --cookies cookies.txt "URL"
```

### IP 被封 (TikTok)
使用代理或 VPN。

## 示例工作流

### 1. 解析 YouTube 视频
```bash
# 1. 获取基本信息
yt-dlp -j "https://www.youtube.com/watch?v=dQw4w9WgXcQ" | jq '{title, view_count, description}'

# 2. 下载字幕
yt-dlp --write-subs --write-auto-subs --sub-lang en --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 2. 下载 B 站视频
```bash
# 1. 查看可用格式
yt-dlp --list-formats "https://www.bilibili.com/video/BV1qH4y1o7UF"

# 2. 下载 (1080p)
yt-dlp -f "30080+30216" "https://www.bilibili.com/video/BV1qH4y1o7UF" -o ~/Downloads/bilibili.mp4
```
