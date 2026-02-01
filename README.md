# Video Downloader API Server

Серверная часть для приложения "Загрузчик видео". Использует yt-dlp с полной поддержкой JS runtime для скачивания видео с YouTube, VK, TikTok и других платформ.

## Деплой на Render (бесплатно)

### Шаг 1: Создай GitHub репозиторий

1. Создай новый репозиторий на GitHub (например, `video-downloader-api`)
2. Загрузи в него содержимое папки `server`:
   ```
   video-downloader-api/
   ├── main.py
   ├── requirements.txt
   ├── Dockerfile
   └── render.yaml
   ```

### Шаг 2: Деплой на Render

1. Зайди на [render.com](https://render.com) и создай аккаунт
2. Нажми "New" → "Web Service"
3. Подключи GitHub и выбери свой репозиторий
4. Настройки:
   - **Name**: video-downloader-api
   - **Environment**: Docker
   - **Plan**: Free
5. Нажми "Create Web Service"

### Шаг 3: Получи URL

После деплоя ты получишь URL вида:
```
https://video-downloader-api-xxxx.onrender.com
```

### Шаг 4: Обнови Flutter приложение

В файле `lib/core/services/video_api_client.dart` замени:
```dart
static const String _baseUrl = 'https://your-video-api.onrender.com';
```
на свой URL.

## API Endpoints

### GET /health
Проверка работоспособности сервера.

**Response:**
```json
{
  "status": "healthy",
  "yt_dlp_version": "2024.11.04"
}
```

### POST /info
Получить информацию о видео.

**Request:**
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
}
```

**Response:**
```json
{
  "success": true,
  "platform": "youtube",
  "data": {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "thumbnail": "https://...",
    "duration": 212,
    "uploader": "Rick Astley",
    "formats": [
      {
        "format_id": "22",
        "quality": "720p",
        "ext": "mp4",
        "filesize": 12345678
      }
    ]
  }
}
```

### POST /download
Получить прямую ссылку на скачивание.

**Request:**
```json
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "quality": "720p"
}
```

**Response:**
```json
{
  "success": true,
  "download_url": "https://...",
  "title": "Rick Astley - Never Gonna Give You Up",
  "ext": "mp4"
}
```

## Локальный запуск

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск
python main.py
```

Сервер запустится на http://localhost:8000

## Важно

- На бесплатном плане Render сервер "засыпает" после 15 минут неактивности
- Первый запрос после "сна" может занять 30-60 секунд
- Для production рекомендуется платный план ($7/месяц)
