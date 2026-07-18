"""
youtube-upload-bot — Bot de Telegram que sube videos a YouTube.
Despliegue: Render (Web Service) o cualquier VPS.
"""

import os
import sys
import json
import asyncio
import logging
import tempfile
import threading
import shutil
import subprocess
from os.path import join, dirname
from dotenv import load_dotenv

load_dotenv(join(dirname(__file__) or ".", ".env"))

from datetime import datetime

from flask import Flask, jsonify

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import FloodWait

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ytbot")

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", 0))
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
PORT = int(os.environ.get("PORT", 8080))

MAX_FILE_SIZE = 2048 * 1024 * 1024  # 2 GB — límite de bots Telegram con @BotFather

# ---------------------------------------------------------------------------
# Estados de conversación (por usuario)
# ---------------------------------------------------------------------------

ST_IDLE = "idle"
ST_TITLE = "awaiting_title"
ST_DESC = "awaiting_desc"

# user_id → { "st": ..., fields }
user_state: dict[int, dict] = {}


def _uid(message: Message) -> int | None:
    """ID del usuario que manda el mensaje."""
    u = message.from_user
    return u.id if u else None


# ---------------------------------------------------------------------------
# YouTube Auth
# ---------------------------------------------------------------------------

def _yt_creds() -> Credentials | None:
    if not all([YT_REFRESH_TOKEN, YT_CLIENT_ID, YT_CLIENT_SECRET]):
        log.error("Faltan variables YOUTUBE_* en el entorno")
        return None
    return Credentials(
        token=None,
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
    )


# ---------------------------------------------------------------------------
# YouTube Upload
# ---------------------------------------------------------------------------

def _upload_video(
    filepath: str, title: str, desc: str = "", is_short: bool = False
) -> tuple[bool, str]:
    """
    Sube un video a YouTube.
    Retorna (éxito, url_si_ok | mensaje_error).
    """
    creds = _yt_creds()
    if not creds:
        return False, "Configuración de YouTube incompleta. El dueño debe configurar YOUTUBE_*."

    try:
        youtube = build("youtube", "v3", credentials=creds)

        snippet = {"title": title, "description": desc}
        if is_short and "#Shorts" not in title and "#shorts" not in title:
            snippet["title"] = f"{title} #Shorts"

        body = {
            "snippet": snippet,
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(filepath, chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status", body=body, media_body=media
        )
        response = request.execute()
        vid = response.get("id", "")
        return True, f"https://youtu.be/{vid}"

    except HttpError as e:
        msg = str(e)
        try:
            body = json.loads(e.content)
            msg = body.get("error", {}).get("message", str(e))
        except Exception:
            pass
        # Errores comunes
        if "quota" in msg.lower():
            msg += " (La cuota de la API se renová diariamente)"
        return False, f"YouTube API: {msg}"

    except Exception as e:
        return False, f"Error inesperado: {e}"


# ---------------------------------------------------------------------------
# Procesamiento de Shorts
# ---------------------------------------------------------------------------

def _process_short(input_path: str) -> str | None:
    """
    Convierte un video a formato Short (vertical 9:16, máx 60s).
    Retorna la ruta del archivo procesado, o None si falla.
    Si el video ya cumple, retorna la misma ruta.
    """
    out_path = input_path + "_short.mp4"

    # Sondear dimensiones y duración
    probe = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", input_path,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if probe.returncode != 0:
        log.warning("ffprobe falló para %s", input_path)
        return None

    info = json.loads(probe.stdout)
    vs = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if not vs:
        return None

    duration = float(info.get("format", {}).get("duration", 0))
    w, h = vs.get("width", 0), vs.get("height", 0)

    # Ya es vertical y corto → usarlo tal cual
    if h > w and duration <= 61:
        return input_path

    target_duration = min(duration, 60)

    # Calcular crop a 9:16
    if w / h > 9 / 16:
        new_w = int(h * 9 / 16)
        x = (w - new_w) // 2
        vf = f"crop={new_w}:{h}:{x}:0,scale=1080:1920"
    else:
        new_h = int(w * 16 / 9)
        y = (h - new_h) // 2
        vf = f"crop={w}:{new_h}:0:{y},scale=1080:1920"

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-t", str(target_duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        log.error("ffmpeg short processing error: %s", result.stderr)
        return None

    return out_path


# ---------------------------------------------------------------------------
# Teclados inline
# ---------------------------------------------------------------------------

def _kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Subir a YouTube", callback_data="yt")],
        [InlineKeyboardButton("📱 Subir como Short", callback_data="short")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


def _kb_title():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Escribir título", callback_data="title_custom")],
        [InlineKeyboardButton("✅ Título automático", callback_data="title_auto")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


def _kb_desc():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Agregar descripción", callback_data="desc_custom")],
        [InlineKeyboardButton("⏭️  Saltar", callback_data="desc_skip")],
        [InlineKeyboardButton("🔙 Volver", callback_data="restart")],
    ])


def _kb_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Subir", callback_data="confirm")],
        [InlineKeyboardButton("🔙 Volver a empezar", callback_data="restart")],
    ])


# ---------------------------------------------------------------------------
# Bot — Handlers
# ---------------------------------------------------------------------------

# Filtro de owner — si OWNER_ID está seteado, solo ese usuario puede usar el bot.
# Pyrogram compone filters con &, |, ~.
owner_filter = filters.user(OWNER_ID) if OWNER_ID else filters.all

bot = Client(
    "ytbot",
    api_id=API_ID or None,
    api_hash=API_HASH or None,
    bot_token=BOT_TOKEN,
    in_memory=True,
)


COMANDOS = """\
🎬 *YouTube Uploader Bot* — Comandos

• `/start` — mensaje de bienvenida
• `/help` — esta lista de comandos
• `/nuevo` — reinicia el proceso (si estás a medio camino)
• `/skip` — salta la descripción del video
• `/cancel` — cancela la operación actual

*¿Cómo funciona?*
1. Mandame un video (o archivo de video)
2. Elegí si es *YouTube* normal o *Short* 📱
3. Poné título (o usá uno automático)
4. Agregá descripción (o saltala)
5. Confirmá y esperá el link
"""


@bot.on_message(filters.command("start") & owner_filter)
async def cmd_start(_c: Client, m: Message):
    """Bienvenida. Muestra intro y primer paso."""
    await m.reply(
        "🎬 *YouTube Uploader Bot*\n\n"
        "Mandame un video y lo subo a tu canal de YouTube.\n\n"
        "Usá `/help` para ver todos los comandos.\n\n"
        "_También soporta Shorts_ 📱",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@bot.on_message(filters.command("help") & owner_filter)
async def cmd_help(_c: Client, m: Message):
    """Lista completa de comandos y guía rápida."""
    await m.reply(COMANDOS, parse_mode=enums.ParseMode.MARKDOWN)


@bot.on_message(filters.command("nuevo") & owner_filter)
async def cmd_nuevo(_c: Client, m: Message):
    """Reinicia el estado del usuario. Útil si el flujo se trabó."""
    uid = _uid(m)
    if uid:
        user_state.pop(uid, None)
    await m.reply("✅ Proceso reiniciado. Mandame un video.")


@bot.on_message(filters.command("cancel") & owner_filter)
async def cmd_cancel(_c: Client, m: Message):
    """Cancela la operación actual y limpia el estado."""
    uid = _uid(m)
    if uid:
        user_state.pop(uid, None)
    await m.reply("❌ Operación cancelada.")


@bot.on_message((filters.video | filters.document) & owner_filter)
async def on_video(_c: Client, m: Message):
    uid = _uid(m)
    if not uid:
        return

    # Si es documento, verificar que sea video
    if m.document and not (m.document.mime_type or "").startswith("video/"):
        await m.reply("❌ Eso no es un video. Mandame un archivo de video.")
        return

    media = m.video or m.document
    size = media.file_size or 0

    if size > MAX_FILE_SIZE:
        await m.reply("❌ El video es muy grande (máx 2 GB).")
        return

    size_mb = size / (1024 * 1024)

    # Guardar estado
    user_state[uid] = {
        "st": ST_IDLE,
        "media_msg_id": m.id,
        "title": None,
        "desc": "",
        "is_short": False,
    }

    await m.reply(
        f"📥 Video recibido ({size_mb:.1f} MB)\n\n¿Qué querés hacer?",
        reply_markup=_kb_main(),
    )


@bot.on_callback_query(owner_filter)
async def on_callback(_c: Client, cb: CallbackQuery):
    uid = cb.from_user.id
    data = cb.data

    if uid not in user_state:
        await cb.answer("Sesión expirada. Mandá un video de nuevo.", show_alert=True)
        return

    s = user_state[uid]
    await cb.answer()

    # ── Cancelar ──────────────────────────────────────────────────────
    if data == "cancel":
        user_state.pop(uid, None)
        await cb.message.edit_text("❌ Cancelado.")

    # ── Elegir tipo ───────────────────────────────────────────────────
    elif data in ("yt", "short"):
        s["is_short"] = data == "short"
        label = "📱 Short" if data == "short" else "🎬 Video"
        await cb.message.edit_text(
            f"{label} seleccionado.\n\n¿Querés ponerle un título?",
            reply_markup=_kb_title(),
        )

    # ── Título ────────────────────────────────────────────────────────
    elif data == "title_custom":
        s["st"] = ST_TITLE
        await cb.message.edit_text(
            "✏️ Escribí el título del video.\n\n"
            "Ej: *Mi video en YouTube*\n\n"
            "_(o /cancel para cancelar)_",
            parse_mode=enums.ParseMode.MARKDOWN,
        )

    elif data == "title_auto":
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        s["title"] = f"Video de Telegram — {now}"
        s["st"] = ST_DESC
        await _after_title(cb.message, s)

    # ── Descripción ───────────────────────────────────────────────────
    elif data == "desc_custom":
        s["st"] = ST_DESC
        await cb.message.edit_text(
            "✏️ Escribí la descripción (o /skip para saltar):"
        )

    elif data == "desc_skip":
        s["desc"] = ""
        s["st"] = ST_IDLE
        await _show_summary(cb.message, s)

    # ── Confirmar ─────────────────────────────────────────────────────
    elif data == "confirm":
        await cb.message.edit_text("⏳ Preparando todo...")
        # Disparar en background
        asyncio.create_task(_do_upload(cb.message, s, uid))

    # ── Reiniciar ─────────────────────────────────────────────────────
    elif data == "restart":
        user_state.pop(uid, None)
        await cb.message.edit_text("✅ Listo. Mandame otro video.")


# ---------------------------------------------------------------------------
# Helpers de flujo
# ---------------------------------------------------------------------------

async def _after_title(msg: Message, s: dict):
    """Después de tener el título, preguntar por descripción."""
    await msg.edit_text(
        f"📌 Título: `{s['title']}`\n\n¿Querés agregar una descripción?",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=_kb_desc(),
    )


async def _show_summary(msg: Message, s: dict):
    """Muestra resumen y pide confirmación final."""
    tipo = "📱 Short" if s["is_short"] else "🎬 Video"
    desc = s.get("desc", "") or "_(sin descripción)_"
    if len(desc) > 120:
        desc = desc[:120] + "…"

    text = (
        f"📋 *Resumen*\n\n"
        f"**Tipo:** {tipo}\n"
        f"**Título:** `{s['title']}`\n"
        f"**Descripción:** {desc}\n\n"
        "¿Todo bien?"
    )
    await msg.edit_text(
        text,
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=_kb_confirm(),
    )


async def _do_upload(msg: Message, s: dict, uid: int):
    """Descarga, procesa (si short) y sube a YouTube."""
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp()
        await msg.edit_text("⬇️  Descargando video de Telegram…")

        original = await bot.get_messages(msg.chat.id, s["media_msg_id"])
        if not original or not (original.video or original.document):
            await msg.edit_text("❌ No se pudo recuperar el video original.")
            user_state.pop(uid, None)
            return

        raw_path = os.path.join(tmp_dir, "input.mp4")
        dl_path = await original.download(file_name=raw_path)
        if not dl_path:
            await msg.edit_text("❌ Error al descargar el video.")
            user_state.pop(uid, None)
            return

        upload_path = dl_path

        # Procesar Short si corresponde
        if s["is_short"]:
            await msg.edit_text("📱 Procesando formato Short…")
            processed = _process_short(dl_path)
            if processed and processed != dl_path:
                upload_path = processed
            elif processed is None:
                await msg.edit_text(
                    "⚠️ No se pudo procesar como Short. "
                    "Se subirá el video original."
                )

        # Subir a YouTube
        await msg.edit_text("⬆️  Subiendo a YouTube… (puede tardar unos minutos)")

        loop = asyncio.get_event_loop()
        ok, result = await loop.run_in_executor(
            None,
            _upload_video,
            upload_path,
            s["title"],
            s.get("desc", ""),
            s["is_short"],
        )

        # Limpiar estado ANTES de notificar para evitar doble envío
        user_state.pop(uid, None)

        if ok:
            await msg.edit_text(
                f"✅ *Video subido con éxito* 🎉\n\n"
                f"🔗 {result}\n\n"
                "Mandame otro video para seguir subiendo.",
                parse_mode=enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        else:
            await msg.edit_text(
                f"❌ *Error al subir:*\n`{result}`\n\n"
                "Mandá el video de nuevo para reintentar.",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

    except FloodWait as e:
        await msg.edit_text(
            f"⏳ Telegram pide esperar {e.value} segundos. Reintentá en un rato."
        )
    except Exception as e:
        log.exception("Error en _do_upload")
        try:
            await msg.edit_text(f"❌ Error inesperado: {e}")
        except Exception:
            pass
        user_state.pop(uid, None)
    finally:
        if tmp_dir:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Captura de texto para título/descripción
# ---------------------------------------------------------------------------

@bot.on_message(
    filters.text
    & ~filters.command("start")
    & ~filters.command("help")
    & ~filters.command("nuevo")
    & ~filters.command("cancel")
    & ~filters.command("skip")
    & owner_filter
)
async def on_text(_c: Client, m: Message):
    uid = _uid(m)
    if uid not in user_state:
        return

    s = user_state[uid]
    text = m.text.strip()

    if s["st"] == ST_TITLE:
        s["title"] = text
        s["st"] = ST_DESC
        await m.reply(
            f"✅ Título guardado: `{text}`\n\n¿Descripción?",
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=_kb_desc(),
        )
    elif s["st"] == ST_DESC:
        s["desc"] = text
        s["st"] = ST_IDLE
        await _show_summary(m, s)


@bot.on_message(filters.command("skip") & owner_filter)
async def cmd_skip(_c: Client, m: Message):
    uid = _uid(m)
    if uid in user_state and user_state[uid].get("st") == ST_DESC:
        s = user_state[uid]
        s["desc"] = ""
        s["st"] = ST_IDLE
        await _show_summary(m, s)


# ---------------------------------------------------------------------------
# Flask — health check para Render
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)


@flask_app.route("/")
@flask_app.route("/health")
def health():
    return jsonify({"ok": True, "bot": "running"})


def _run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        log.error("Falta BOT_TOKEN en variables de entorno")
        sys.exit(1)

    log.info("Iniciando Flask en puerto %d …", PORT)
    t = threading.Thread(target=_run_flask, daemon=True)
    t.start()

    log.info("Iniciando bot de Telegram …")
    bot.run()  # blocking — mantiene el proceso vivo


if __name__ == "__main__":
    main()
