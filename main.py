"""
Video Downloader API Server
FastAPI сервер для скачивания видео через yt-dlp с полной поддержкой JS runtime.

Endpoints:
- GET /health - проверка работоспособности
- POST /info - получить информацию о видео
- POST /download - получить прямую ссылку на видео
"""

import os
import json
import asyncio
import hashlib
import time
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, HttpUrl
import yt_dlp

app = FastAPI(
    title="Video Downloader API",
    description="API для скачивания видео с YouTube, VK, TikTok и других платформ",
    version="1.0.0"
)

# CORS для доступа из приложения
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Кэш для информации о видео (в памяти, для простоты)
video_cache = {}
CACHE_TTL = 300  # 5 минут


class VideoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None
    quality: Optional[str] = "best"  # best, 1080p, 720p, 480p, 360p, audio


def get_cache_key(url: str) -> str:
    """Создать ключ кэша для URL."""
    return hashlib.md5(url.encode()).hexdigest()


def is_cache_valid(cache_entry: dict) -> bool:
    """Проверить, валиден ли кэш."""
    if not cache_entry:
        return False
    return time.time() - cache_entry.get("timestamp", 0) < CACHE_TTL


def detect_platform(url: str) -> str:
    """Определить платформу по URL."""
    url_lower = url.lower()
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'youtube'
    elif 'vk.com' in url_lower or 'vk.ru' in url_lower or 'vkvideo.ru' in url_lower:
        return 'vk'
    elif 'tiktok.com' in url_lower:
        return 'tiktok'
    elif 'rutube.ru' in url_lower:
        return 'rutube'
    elif 'instagram.com' in url_lower:
        return 'instagram'
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        return 'twitter'
    elif 'ok.ru' in url_lower:
        return 'ok'
    elif 'dzen.ru' in url_lower:
        return 'dzen'
    return 'generic'


def get_ydl_opts(platform: str) -> dict:
    """Получить оптимальные опции yt-dlp для платформы."""
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': 30,
        'retries': 3,
        'fragment_retries': 3,
    }

    chrome_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

    if platform == 'youtube':
        return {
            **base_opts,
            'socket_timeout': 60,
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


@app.get("/")
async def root():
    """Главная страница."""
    return {
        "service": "Video Downloader API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "info": "POST /info",
            "download": "POST /download"
        }
    }


@app.get("/health")
async def health_check():
    """Проверка работоспособности сервера."""
    try:
        # Проверяем что yt-dlp работает
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
    """
    Получить информацию о видео.

    Возвращает: название, длительность, форматы, превью и т.д.
    """
    url = request.url
    cache_key = get_cache_key(url)

    # Проверяем кэш
    if cache_key in video_cache and is_cache_valid(video_cache[cache_key]):
        return video_cache[cache_key]["data"]

    platform = detect_platform(url)
    ydl_opts = get_ydl_opts(platform)
    ydl_opts['extract_flat'] = False

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if not info:
                raise HTTPException(status_code=404, detail="Видео не найдено")

            # Парсим форматы
            formats = []
            for f in info.get("formats", []):
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")

                # Аудио
                if vcodec == "none" and acodec != "none":
                    formats.append({
                        "format_id": f.get("format_id"),
                        "ext": f.get("ext", "mp3"),
                        "quality": "audio",
                        "resolution": "Audio only",
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                        "has_audio": True,
                        "has_video": False,
                        "url": f.get("url"),
                    })
                # Видео
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
                        "url": f.get("url"),
                    })

            # Сортируем по качеству
            formats = sorted(
                [f for f in formats if f.get("height", 0) > 0 or f.get("quality") == "audio"],
                key=lambda x: x.get("height", 0),
                reverse=True
            )

            # Убираем дубликаты
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

            # Кэшируем
            video_cache[cache_key] = {
                "data": result,
                "timestamp": time.time()
            }

            return result

    except yt_dlp.DownloadError as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "bot" in error_msg.lower():
            raise HTTPException(status_code=403, detail="Платформа требует авторизацию")
        elif "Private" in error_msg:
            raise HTTPException(status_code=403, detail="Видео приватное")
        elif "unavailable" in error_msg.lower():
            raise HTTPException(status_code=404, detail="Видео недоступно или удалено")
        elif "geo" in error_msg.lower() or "country" in error_msg.lower():
            raise HTTPException(status_code=403, detail="Видео недоступно в вашем регионе")
        else:
            raise HTTPException(status_code=500, detail=f"Ошибка извлечения: {error_msg[:200]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


@app.post("/download")
async def get_download_url(request: DownloadRequest):
    """
    Получить прямую ссылку на скачивание видео.

    Параметры:
    - url: URL видео
    - format_id: ID конкретного формата (опционально)
    - quality: Желаемое качество: best, 1080p, 720p, 480p, 360p, audio
    """
    url = request.url
    format_id = request.format_id
    quality = request.quality or "best"

    platform = detect_platform(url)
    ydl_opts = get_ydl_opts(platform)

    # Определяем формат
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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if not info:
                raise HTTPException(status_code=404, detail="Видео не найдено")

            # Получаем URL для скачивания
            download_url = info.get("url")

            # Если URL нет в корне, ищем в formats
            if not download_url:
                formats = info.get("formats", [])
                if formats:
                    # Берём последний (обычно лучший после сортировки)
                    download_url = formats[-1].get("url")

            # Для merged форматов может быть requested_formats
            if not download_url:
                requested = info.get("requested_formats", [])
                if requested:
                    # Возвращаем оба URL (video и audio)
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
                raise HTTPException(status_code=500, detail="Не удалось получить ссылку на скачивание")

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
            raise HTTPException(status_code=403, detail="Платформа требует авторизацию")
        elif "Private" in error_msg:
            raise HTTPException(status_code=403, detail="Видео приватное")
        elif "unavailable" in error_msg.lower():
            raise HTTPException(status_code=404, detail="Видео недоступно")
        else:
            raise HTTPException(status_code=500, detail=f"Ошибка: {error_msg[:200]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
