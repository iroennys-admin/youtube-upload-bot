#!/usr/bin/env python3
"""
auth_youtube.py — Obtiene refresh token de YouTube.

Flujo: generamos link → lo abrís en tu navegador → autorizás →
       Google redirige a http://localhost/?code=... →
       copiás el código de la URL → lo pasamos acá.

Uso:
    python3 auth_youtube.py --json '{"installed": {...}}'
    # te muestra un link, lo abrís, autorizás, copiás el código de la URL
    python3 auth_youtube.py --json '{"installed": {...}}' --code "4/0A..."
"""

import os
import sys
import json
import requests

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"


def main():
    print("=" * 60)
    print("  Autenticación de YouTube")
    print("=" * 60)
    print()

    client_id = ""
    client_secret = ""

    if "--json" in sys.argv:
        idx = sys.argv.index("--json") + 1
        raw = json.loads(sys.argv[idx])
        for key in ("web", "installed"):
            if key in raw:
                client_id = raw[key]["client_id"]
                client_secret = raw[key]["client_secret"]
                break
    else:
        client_id = os.environ.get("YOUTUBE_CLIENT_ID") or input("Client ID: ").strip()
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET") or input("Client Secret: ").strip()

    # Generar URL de autorización — redirect a localhost
    # Google redirige acá con el código en la URL
    auth_url = (
        "https://accounts.google.com/o/oauth2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri=http://localhost"
        f"&scope={SCOPES.replace(' ', '+')}"
        f"&response_type=code"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print("1️⃣  Abrí este link en tu navegador:")
    print()
    print(auth_url)
    print()
    print("2️⃣  Iniciá sesión con tu cuenta de YouTube")
    print("3️⃣  Dale permisos a la app")
    print("4️⃣  Google te va a redirigir a una página que dice")
    print("    'This site can't be reached' — NO CERRES ESA PÁGINA")
    print()
    print("5️⃣  MIRÁ LA BARRA DE DIRECCIONES del navegador")
    print("    Vas a ver algo como:")
    print("    http://localhost/?code=4/0A...&scope=...")
    print()
    print("6️⃣  Copiá TODO lo que está después de ?code=")
    print("    (hasta antes del &) — es el código")
    print()

    code = ""
    if "--code" in sys.argv:
        idx = sys.argv.index("--code") + 1
        code = sys.argv[idx]

    if not code:
        print("👉 Cuando tengas el código, corre:")
        print(f'   python3 auth_youtube.py --json \'{{"installed": {{"client_id": "{client_id}", "client_secret": "{client_secret}"}}}}\' --code "4/0A...EL_CODIGO"')
        return

    print("⏳ Intercambiando código por tokens…")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": "http://localhost",
    })

    tokens = r.json()

    if "refresh_token" not in tokens:
        print(f"❌ Error: {tokens}")
        print()
        print("💡 Probá agregando riroennis@gmail.com como usuario de prueba en")
        print("   https://console.cloud.google.com/apis/credentials/consent")
        return

    refresh_token = tokens["refresh_token"]

    print()
    print("=" * 60)
    print("  ✅ Autenticación exitosa!")
    print("=" * 60)
    print()
    print("Agregá estas 3 variables a Render (o a tu .env):")
    print()
    print(f"YOUTUBE_CLIENT_ID={client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={refresh_token}")
    print()
    print("⚠️  Guardalo seguro. No expira.")


if __name__ == "__main__":
    main()
