"""
Lectura de carruseles de Instagram (y otros links) + lectura de capturas con visión.

Instagram no da una API pública para leer un post ajeno, pero:
  1. El endpoint de EMBED (`/embed/captioned/`) devuelve HTML público con el caption.
  2. Las meta tags og: del post traen título/descripción/imagen de portada.
Con eso sacamos el CAPTION y el ángulo del carrusel.

El texto que va DENTRO de las imágenes (lo típico de un carrusel) no viaja en el HTML:
para eso se usa VISIÓN — el usuario adjunta capturas y Claude las lee.
"""
from __future__ import annotations

import base64
import html as html_mod
import json
import os
import re

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
VISION_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")


class IGError(Exception):
    pass


# ---------------- Leer el link ----------------
def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(text).strip()


def _shortcode(url: str) -> str | None:
    m = re.search(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else None


def read_link(url: str) -> dict:
    """
    Devuelve {ok, caption, title, image, source, note}.
    Intenta el embed de Instagram y, si no, las meta og: de la página.
    """
    url = (url or "").strip()
    if not url:
        raise IGError("Falta el link.")

    headers = {"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}
    code = _shortcode(url)

    # 1) Embed de Instagram (público, trae el caption)
    if code:
        try:
            emb = f"https://www.instagram.com/p/{code}/embed/captioned/"
            r = requests.get(emb, headers=headers, timeout=20)
            if r.status_code < 400 and r.text:
                htm = r.text
                cap = ""
                m = re.search(r'class="Caption"(.*?)</div>', htm, re.S)
                if m:
                    seg = m.group(1)
                    seg = re.sub(r'<div class="CaptionUsername".*?</div>', "", seg, flags=re.S)
                    cap = _clean(seg)
                if not cap:
                    m2 = re.search(r'"caption"\s*:\s*"(.*?)"(?:,|\})', htm, re.S)
                    if m2:
                        try:
                            cap = json.loads('"' + m2.group(1) + '"')
                        except json.JSONDecodeError:
                            cap = _clean(m2.group(1))
                img = ""
                mi = re.search(r'class="EmbeddedMediaImage"[^>]*src="([^"]+)"', htm)
                if mi:
                    img = html_mod.unescape(mi.group(1))
                if cap:
                    return {"ok": True, "caption": cap, "title": "", "image": img,
                            "source": "instagram-embed",
                            "note": "Leí el CAPTION del post. El texto dentro de las imágenes "
                                    "no viaja en el HTML: adjunta capturas para leerlo."}
        except requests.RequestException:
            pass

    # 2) Meta tags og: de la página
    try:
        r = requests.get(url, headers=headers, timeout=20)
        htm = r.text or ""
        def og(prop):
            m = re.search(r'<meta[^>]+property=["\']og:%s["\'][^>]+content=["\'](.*?)["\']' % prop, htm, re.S)
            if not m:
                m = re.search(r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:%s["\']' % prop, htm, re.S)
            return html_mod.unescape(m.group(1)).strip() if m else ""
        desc, title, image = og("description"), og("title"), og("image")
        if desc or title:
            return {"ok": True, "caption": desc, "title": title, "image": image,
                    "source": "og-meta",
                    "note": "Leí la descripción pública del post. Para el texto dentro de "
                            "las imágenes, adjunta capturas."}
    except requests.RequestException as e:
        raise IGError(f"No pude abrir el link: {e}") from e

    return {"ok": False, "caption": "", "title": "", "image": "", "source": "",
            "note": "El sitio no entregó el contenido (Instagram bloquea la lectura "
                    "desde servidores). Adjunta capturas del carrusel y las leo."}


# ---------------- Leer capturas con visión ----------------
def _headers() -> dict:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise IGError("Falta ANTHROPIC_API_KEY en el backend.")
    return {"x-api-key": key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"}


VISION_PROMPT = """Estas imágenes son los slides de un carrusel de Instagram, en orden.
Transcribe FIELMENTE el texto de cada slide y resume su estructura.

Devuelve SOLO un JSON válido:
{
  "slides": ["texto completo del slide 1", "texto del slide 2", "..."],
  "tema": "de qué trata el carrusel, en una frase",
  "angulo": "el ángulo/gancho que usa y por qué funciona (1-2 frases)",
  "formato": "cómo está armado visualmente (ej: infografía con números grandes, foto de fondo con texto centrado...)"
}
Si un slide no tiene texto, describe brevemente la imagen entre corchetes."""


def read_images(images: list[tuple[str, bytes]]) -> dict:
    """
    images: lista de (media_type, bytes). Devuelve {slides:[...], tema, angulo, formato}.
    """
    if not images:
        raise IGError("No hay imágenes que leer.")
    if len(images) > 12:
        images = images[:12]

    content = []
    for media_type, raw in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.b64encode(raw).decode("ascii")},
        })
    content.append({"type": "text", "text": VISION_PROMPT})

    payload = {"model": VISION_MODEL, "max_tokens": 3000,
               "messages": [{"role": "user", "content": content}]}
    r = requests.post(ANTHROPIC_URL, headers=_headers(), json=payload, timeout=120)
    if r.status_code >= 400:
        raise IGError(f"Visión {r.status_code}: {r.text[:400]}")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise IGError(f"Respuesta sin JSON: {text[:300]}")
    try:
        parsed = json.loads(text[start:end + 1], strict=False)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", text[start:end + 1])
        parsed = json.loads(cleaned, strict=False)
    return parsed
