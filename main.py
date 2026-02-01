"""
Video Downloader API Server
FastAPI server for downloading videos via yt-dlp with full JS runtime support.

Endpoints:
- GET /health - health check
- POST /info - get video info
- POST /download - get direct download URL
- POST /stream - stream video directly (no temp file, starts immediately)
"""

import os
import hashlib
import time
import subprocess
import asyncio
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import yt_dlp

app = FastAPI(
    title="Video Downloader API",
    description="API for downloading videos from YouTube, VK, TikTok and other platforms",
    version="1.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)

video_cache = {}
CACHE_TTL = 300


class VideoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None
    quality: Optional[str] = "best"


class StreamRequest(BaseModel):
    url: str
    format_id: Optional[str] = None
    quality: Optional[str] = "best"


def get_cache_key(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def is_cache_valid(cache_entry: dict) -> bool:
    if not cache_entry:
        return False
    return time.time() - cache_entry.get("timestamp", 0) < CACHE_TTL


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'youtube'
    elif 'vk.com' in url_lower or 'vk.ru' in url_lower or 'vkvideo.ru' in url_lower:
        return 'vk'
    elif 'tiktok.com' in url_lower:
        return 'tiktok'
    elif 'rutube.ru' in url_lower:
        return 'rutube'
    elif 'ok.ru' in url_lower:
        return 'ok'
    elif 'dzen.ru' in url_lower:
        return 'dzen'
    return 'generic'


def get_ydl_opts(platform: str) -> dict:
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': 60,
        'retries': 5,
        'fragment_retries': 5,
        'extractor_retries': 3,
    }

    chrome_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'

    if platform == 'youtube':
        return {
            **base_opts,
            'socket_timeout': 90,
            'http_headers': {
                'User-Agent': chrome_ua,
                'Accept-Language': 'en-US,en;q=0.9',
            },
        }
    elif platform == 'vk':
        return {
            **base_opts,
            'http_headers': {
                'User-Agent': chrome_ua,
                'Accept-Language': 'ru-RU,ru;q=0.9',
                'Referer': 'https://vk.com/',
            },
        }
    elif platform == 'tiktok':
        return {
            **base_opts,
            'http_headers': {
                'User-Agent': 'TikTok 33.0.0 rv:330018 (iPhone; iOS 17.3; en_US) Cronet',
                'Accept': '*/*',
            },
        }
    else:
        return {
            **base_opts,
            'http_headers': {
                'User-Agent': chrome_ua,
            },
        }


def _extract_info_sync(url: str, ydl_opts: dict):
    """Синхронное извлечение информации о видео."""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


@app.get("/")
async def root():
    return {
        "service": "Video Downloader API",
        "version": "1.3.0",
        "endpoints": {
            "health": "/health",
            "info": "POST /info",
            "download": "POST /download",
            "stream": "POST /stream"
        }
    }


@app.get("/health")
async def health_check():
    try:
        version = yt_dlp.version.__version__
        return {
            "status": "healthy",
            "yt_dlp_version": version,
            "timestamp": int(time.time())
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.post("/info")
async def get_video_info(request: VideoRequest):
    url = request.url
    cache_key = get_cache_key(url)

    if cache_key in video_cache and is_cache_valid(video_cache[cache_key]):
        return video_cache[cache_key]["data"]

    platform = detect_platform(url)
    ydl_opts = get_ydl_opts(platform)
    ydl_opts['extract_flat'] = False

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, _extract_info_sync, url, ydl_opts)

        if not info:
            raise HTTPException(status_code=404, detail="Video not found")

        formats = []
        for f in info.get("formats", []):
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")

            if vcodec == "none" and acodec != "none":
                formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext", "mp3"),
                    "quality": "audio",
                    "resolution": "Audio only",
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": True,
                    "has_video": False,
                    "height": 0,
                })
            elif vcodec != "none":
                height = f.get("height", 0) or 0
                formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext", "mp4"),
                    "quality": f"{height}p" if height else "unknown",
                    "resolution": f.get("resolution", f"{height}p"),
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "has_audio": acodec != "none",
                    "has_video": True,
                    "height": height,
                })

        formats = sorted(
            [f for f in formats if f.get("height", 0) > 0 or f.get("quality") == "audio"],
            key=lambda x: x.get("height", 0),
            reverse=True
        )

        seen = set()
        unique_formats = []
        for f in formats:
            q = f["quality"]
            if q not in seen:
                seen.add(q)
                unique_formats.append(f)

        result = {
            "success": True,
            "platform": platform,
            "data": {
                "id": info.get("id"),
                "title": info.get("title", "Unknown"),
                "description": (info.get("description") or "")[:500],
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", "Unknown"),
                "view_count": info.get("view_count"),
                "webpage_url": info.get("webpage_url", url),
                "formats": unique_formats[:10],
            }
        }

        video_cache[cache_key] = {
            "data": result,
            "timestamp": time.time()
        }

        return result

    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "bot" in error_msg.lower():
            raise HTTPException(status_code=403, detail="Platform requires authorization")
        elif "Private" in error_msg:
            raise HTTPException(status_code=403, detail="Video is private")
        elif "unavailable" in error_msg.lower():
            raise HTTPException(status_code=404, detail="Video unavailable or deleted")
        elif "geo" in error_msg.lower() or "country" in error_msg.lower():
            raise HTTPException(status_code=403, detail="Video not available in your region")
        else:
            raise HTTPException(status_code=500, detail=f"Extraction error: {error_msg[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.post("/download")
async def get_download_url(request: DownloadRequest):
    url = request.url
    format_id = request.format_id
    quality = request.quality or "best"

    platform = detect_platform(url)
    ydl_opts = get_ydl_opts(platform)

    if format_id:
        format_spec = format_id
    elif quality == "audio":
        format_spec = "bestaudio/best"
    elif quality == "best":
        format_spec = "best/bestvideo+bestaudio"
    elif quality in ["1080p", "720p", "480p", "360p"]:
        height = quality.replace("p", "")
        format_spec = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
    else:
        format_spec = "best"

    ydl_opts['format'] = format_spec

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, _extract_info_sync, url, ydl_opts)

        if not info:
            raise HTTPException(status_code=404, detail="Video not found")

        download_url = info.get("url")

        if not download_url:
            formats = info.get("formats", [])
            if formats:
                download_url = formats[-1].get("url")

        if not download_url:
            requested = info.get("requested_formats", [])
            if requested:
                video_url = None
                audio_url = None
                for f in requested:
                    if f.get("vcodec") != "none":
                        video_url = f.get("url")
                    if f.get("acodec") != "none":
                        audio_url = f.get("url")

                if video_url:
                    return {
                        "success": True,
                        "platform": platform,
                        "title": info.get("title", "video"),
                        "ext": info.get("ext", "mp4"),
                        "download_url": video_url,
                        "audio_url": audio_url,
                        "needs_merge": audio_url is not None and video_url != audio_url,
                        "duration": info.get("duration"),
                        "filesize": info.get("filesize") or info.get("filesize_approx"),
                    }

        if not download_url:
            raise HTTPException(status_code=500, detail="Could not get download URL")

        return {
            "success": True,
            "platform": platform,
            "title": info.get("title", "video"),
            "ext": info.get("ext", "mp4"),
            "download_url": download_url,
            "audio_url": None,
            "needs_merge": False,
            "duration": info.get("duration"),
            "filesize": info.get("filesize") or info.get("filesize_approx"),
        }

    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "bot" in error_msg.lower():
            raise HTTPException(status_code=403, detail="Platform requires authorization")
        elif "Private" in error_msg:
            raise HTTPException(status_code=403, detail="Video is private")
        elif "unavailable" in error_msg.lower():
            raise HTTPException(status_code=404, detail="Video unavailable")
        else:
            raise HTTPException(status_code=500, detail=f"Error: {error_msg[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.post("/stream")
async def stream_download(request: StreamRequest):
    """
    Stream video directly using yt-dlp pipe.
    Starts streaming immediately without waiting for full download.
    """
    url = request.url
    format_id = request.format_id
    quality = request.quality or "best"

    platform = detect_platform(url)

    # Сначала получаем информацию о видео для имени файла
    ydl_opts = get_ydl_opts(platform)

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(executor, _extract_info_sync, url, ydl_opts)

        if not info:
            raise HTTPException(status_code=404, detail="Video not found")

        title = info.get("title", "video")
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()[:50]
        filename = f"{safe_title}.mp4"
        duration = info.get("duration", 0)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get video info: {str(e)[:100]}")

    # Определяем формат для yt-dlp
    if format_id:
        format_spec = format_id
    elif quality == "audio":
        format_spec = "bestaudio[ext=m4a]/bestaudio/best"
    elif quality == "best":
        # Для стриминга предпочитаем форматы где видео и аудио вместе
        format_spec = "best[ext=mp4]/best"
    elif quality in ["1080p", "720p", "480p", "360p"]:
        height = quality.replace("p", "")
        format_spec = f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
    else:
        format_spec = "best[ext=mp4]/best"

    # Строим команду yt-dlp для вывода в stdout
    cmd = [
        "yt-dlp",
        "-f", format_spec,
        "-o", "-",  # Вывод в stdout
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        url
    ]

    # Добавляем user-agent в зависимости от платформы
    if platform == 'youtube':
        cmd.extend(["--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36"])
    elif platform == 'vk':
        cmd.extend(["--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36"])
        cmd.extend(["--referer", "https://vk.com/"])
    elif platform == 'tiktok':
        cmd.extend(["--user-agent", "TikTok 33.0.0 rv:330018 (iPhone; iOS 17.3; en_US) Cronet"])

    async def generate():
        """Генератор для стриминга данных от yt-dlp."""
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Читаем и отдаём данные чанками
            while True:
                chunk = await process.stdout.read(64 * 1024)  # 64KB чанки
                if not chunk:
                    break
                yield chunk

            # Проверяем код возврата
            await process.wait()

            if process.returncode != 0:
                stderr = await process.stderr.read()
                error_msg = stderr.decode('utf-8', errors='ignore')[:200]
                # Логируем ошибку, но не можем отправить её клиенту после начала стриминга
                print(f"yt-dlp error: {error_msg}")

        except Exception as e:
            print(f"Stream error: {e}")
        finally:
            if process and process.returncode is None:
                try:
                    process.kill()
                except:
                    pass

    return StreamingResponse(
        generate(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Video-Title": title[:100],
            "X-Video-Duration": str(duration),
            "Transfer-Encoding": "chunked",
        }
    )


# Для совместимости оставляем старый endpoint
@app.post("/proxy-download")
async def proxy_download(request: StreamRequest):
    """Redirect to stream endpoint for backwards compatibility."""
    return await stream_download(request)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
