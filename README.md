# YouTube Uploader Bot 🎬

Bot de Telegram que descarga videos y los sube a YouTube. Soporta videos normales y Shorts.

Hecho con **Pyrogram** (MTProto) + **YouTube Data API v3** + **ffmpeg**.

---

## ⚙️ Requisitos

- Python 3.10+
- ffmpeg (se instala automáticamente en Render)
- Token de bot de [@BotFather](https://t.me/BotFather)
- API ID y API Hash de [my.telegram.org](https://my.telegram.org/apps)
- Proyecto en [Google Cloud Console](https://console.cloud.google.com/) con YouTube Data API v3 habilitada
- Credenciales OAuth 2.0 (Desktop application)

---

## 🚀 Instalación

```bash
# Clonar
git clone <repo> && cd youtube-upload-bot

# Dependencias
pip install -r requirements.txt

# Configurar credenciales
cp .env.example .env
# Editar .env con tus datos

# Obtener refresh token de YouTube
python auth_youtube.py

# Iniciar
python bot.py
```

---

## 📖 Comandos del Bot

| Comando | Descripción |
|---------|-------------|
| `/start` | Mensaje de bienvenida |
| `/help` | Lista completa de comandos y guía |
| `/nuevo` | Reinicia el proceso (si se trabó) |
| `/skip` | Salta la descripción del video |
| `/cancel` | Cancela la operación actual |

## 🔄 Flujo de uso

```
1. Enviás un video al bot
2. El bot lo descarga y muestra opciones:
   [🎬 YouTube] [📱 Short] [❌ Cancelar]
3. Elegís tipo → definís título (o automático)
4. Agregás descripción (o la saltás)
5. Confirmás → el bot sube a YouTube
6. Recibís link del video publicado 🎉
```

Todo con **botones inline**. No necesitás escribir comandos salvo que quieras.

---

## 📁 Estructura del proyecto

```
youtube-upload-bot/
├── bot.py              # Bot principal (Telegram + YouTube + Flask)
├── auth_youtube.py     # Script para obtener refresh token (correr 1 vez)
├── requirements.txt    # Dependencias Python
├── render.yaml         # Config para deploy en Render
├── .env                # Variables de entorno (local)
├── .gitignore          # .env excluido de git
└── README.md           # Esta documentación
```

---

## 🔧 Variables de Entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `API_ID` | ✅ | De my.telegram.org/apps |
| `API_HASH` | ✅ | De my.telegram.org/apps |
| `BOT_TOKEN` | ✅ | De @BotFather |
| `OWNER_ID` | ✅ | Tu ID de Telegram (solo vos usás el bot) |
| `YOUTUBE_CLIENT_ID` | ✅ | De Google Cloud Console |
| `YOUTUBE_CLIENT_SECRET` | ✅ | De Google Cloud Console |
| `YOUTUBE_REFRESH_TOKEN` | ✅ | Se obtiene con `auth_youtube.py` |
| `PORT` | ❌ | Puerto para Flask (default: 8080, Render lo setea solo) |

---

## ☁️ Deploy en Render

1. Subí el repo a GitHub
2. En [Render Dashboard](https://dashboard.render.com/) → **New Web Service**
3. Conectá tu repo
4. Render detecta `render.yaml` automáticamente o configurá:
   - **Runtime:** Python
   - **Build Command:** `apt-get update -qq && apt-get install -y -qq ffmpeg && pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. Agregá todas las variables de entorno (API_ID, API_HASH, BOT_TOKEN, OWNER_ID, YOUTUBE_*)

> ⚠️ Las variables `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` y `YOUTUBE_REFRESH_TOKEN` son obligatorias. Sin ellas el bot no puede subir videos.

---

## 📱 Shorts

El bot procesa automáticamente los Shorts:

- **Detección:** si el video ya es vertical (9:16) y dura menos de 60s, se sube directo
- **Conversión:** si no cumple, ffmpeg lo recorta a 1080×1920 y limita a 60s
- **Etiqueta:** agrega `#Shorts` al título automáticamente

---

## 🧠 Arquitectura

```
Telegram ←→ Pyrogram (MTProto) → Bot lógico → YouTube Data API v3
                         │
                    descarga video
                         │
                    ffmpeg (shorts)
                         │
                    subida a YouTube
```

- **Pyrogram** se conecta directo por MTProto (más rápido que Bot API HTTP)
- **Flask** corre en un thread separado solo para el health check de Render
- La subida a YouTube usa **upload resumable** (chunks grandes, tolera cortes)
- El **estado de conversación** vive en memoria (bot personal, no necesita DB)

---

## 🔐 Seguridad

- `OWNER_ID` restringe el bot a un solo usuario
- Las credenciales van en `.env` (excluido de git)
- En Render se usan variables de entorno cifradas
- El refresh token de YouTube no expira (salvo que revoques el acceso)
- Archivos temporales se borran después de cada subida

---

## 🐛 Manejo de errores

| Error | Qué pasa |
|---|---|
| Video > 2 GB | Rechazado con mensaje |
| No es video | Rechazado |
| Cuota YouTube excedida | Mensaje claro, se renueva al día siguiente |
| FloodWait de Telegram | Espera automática (Pyrogram) |
| Faltan credenciales | Bot arranca pero rechaza subidas con mensaje explicativo |
| Error de red inesperado | Se limpia el estado, se informa al usuario |

---

## 📄 Licencia

MIT
