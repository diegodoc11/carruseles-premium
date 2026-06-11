#!/usr/bin/env python3
"""
telegram_enviar.py — Envia un carrusel Premium (Nano Banana Pro) al celular via un bot de Telegram.

Hermano del sender de /carruseles pero INDEPENDIENTE: usa el patron carousel-NN.png
y la estructura outputs/bundles/<id>/carousel/ del proyecto Premium.

Uso:
  # Obtener tu chat id (despues de escribirle "hola" a tu bot):
  python telegram_enviar.py --proj-dir <PROJ> --get-chat-id

  # Enviar el carrusel de un bundle concreto:
  python telegram_enviar.py --proj-dir <PROJ> --dir "<...>/outputs/bundles/<id>/carousel"

  # Con caption (se envia como mensaje tras las imagenes):
  python telegram_enviar.py --proj-dir <PROJ> --dir "<...>/carousel" --titulo "..." --mensaje-final "<...>/caption-ig.txt"

  # Calidad original (como archivo, sin compresion de Telegram):
  python telegram_enviar.py --proj-dir <PROJ> --dir "<...>/carousel" --doc

Token y chat id se leen de config.json (telegram_bot_token / telegram_chat_id)
o de las variables de entorno TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.
"""

import argparse
import json
import re
import sys
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path


def _api(token, method, fields=None, files=None, timeout=60):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if not files:
        data = json.dumps(fields or {}).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"})
    else:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in (fields or {}).items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        for name, filename, content in files:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{name}\"; filename=\"{filename}\"\r\n"
                     f"Content-Type: application/octet-stream\r\n\r\n").encode()
            body += content + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def load_creds(proj_dir):
    import os
    envp = proj_dir / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    cfg_path = proj_dir / "config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        token = token or cfg.get("telegram_bot_token")
        chat_id = chat_id or cfg.get("telegram_chat_id")
    return token, chat_id


def latest_carousel(proj_dir):
    """Carpeta carousel/ del bundle mas reciente en outputs/bundles/."""
    bundles = proj_dir / "outputs" / "bundles"
    if not bundles.exists():
        return None
    cands = sorted([d for d in bundles.glob("*/carousel") if d.is_dir()])
    return cands[-1] if cands else None


def _num(p):
    m = re.search(r"(\d+)", p.stem)
    return int(m.group(1)) if m else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proj-dir", default=".")
    ap.add_argument("--dir", default=None,
                    help="Carpeta con las laminas carousel-NN.png (default: bundle mas reciente)")
    ap.add_argument("--titulo", default=None)
    ap.add_argument("--get-chat-id", action="store_true")
    ap.add_argument("--doc", action="store_true",
                    help="Enviar como archivo (calidad original, sin compresion)")
    ap.add_argument("--mensaje-final", default=None,
                    help="Ruta a .txt/.md; su contenido se envia como mensaje tras las fotos (caption IG).")
    args = ap.parse_args()

    proj_dir = Path(args.proj_dir).resolve()
    token, chat_id = load_creds(proj_dir)

    if not token:
        print("❌ Falta el token (config.json -> telegram_bot_token o TELEGRAM_BOT_TOKEN).")
        sys.exit(1)

    if args.get_chat_id:
        r = _api(token, "getUpdates")
        chats = {}
        for upd in r.get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or {}
            ch = msg.get("chat")
            if ch:
                chats[ch["id"]] = ch.get("first_name") or ch.get("title") or ch.get("username") or "?"
        if chats:
            print("✅ Chats encontrados (pon el id en config.json -> telegram_chat_id):")
            for cid, name in chats.items():
                print(f"   chat_id = {cid}   ({name})")
        else:
            print("⚠️  No hay mensajes recientes. Escríbele 'hola' a tu bot y reintenta.")
        return

    if not chat_id:
        print("❌ Falta el chat id. Corre con --get-chat-id primero.")
        sys.exit(1)

    set_dir = Path(args.dir).resolve() if args.dir else latest_carousel(proj_dir)
    if not set_dir or not set_dir.exists():
        print(f"❌ No encontré la carpeta del carrusel: {set_dir}")
        sys.exit(1)

    slides = sorted(set_dir.glob("carousel-*.png"), key=_num)
    if not slides:
        print(f"❌ No hay laminas (carousel-NN.png) en {set_dir}")
        sys.exit(1)

    titulo = args.titulo or set_dir.parent.name
    _api(token, "sendMessage", {
        "chat_id": chat_id,
        "text": f"📲 {titulo} — {len(slides)} slides (en orden)."
    })

    method = "sendDocument" if args.doc else "sendPhoto"
    field = "document" if args.doc else "photo"
    ok = 0
    for i, s in enumerate(slides, 1):
        content = s.read_bytes()
        r = _api(token, method,
                 fields={"chat_id": chat_id, "caption": f"{i}/{len(slides)}"},
                 files=[(field, s.name, content)])
        if r.get("ok"):
            ok += 1
            print(f"  ✅ Enviado {i}/{len(slides)}: {s.name}")
        else:
            print(f"  ⚠️  Error en {s.name}: {r.get('description')}")
        time.sleep(0.4)

    print(f"\n✅ {ok}/{len(slides)} slides enviados a tu Telegram.")

    if args.mensaje_final:
        mf_path = Path(args.mensaje_final)
        if not mf_path.is_absolute():
            mf_path = proj_dir / mf_path
        if mf_path.exists():
            texto = mf_path.read_text(encoding="utf-8")
            chunks = [texto[i:i+4000] for i in range(0, len(texto), 4000)]
            for chunk in chunks:
                _api(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": "true",
                })
                time.sleep(0.4)
            print(f"  ✅ Caption enviado ({len(texto)} chars).")
        else:
            print(f"  ⚠️  No encontré {mf_path}")


if __name__ == "__main__":
    main()
