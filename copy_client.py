"""
Generación de copy para los carruseles usando Claude (Anthropic).

Produce, para un tema dado: un gancho, el texto de cada slide, la bajada/caption
del post y hashtags. Todo en español y con el tono de Flowback.

Variables de entorno:
  ANTHROPIC_API_KEY = sk-ant-...
  ANTHROPIC_MODEL   = (opcional) id del modelo; ajústalo si cambia.
  BRAND_CONTEXT     = (opcional) descripción de la marca para afinar el tono.
"""
from __future__ import annotations

import json
import os
import re
import requests

import brand as brand_mod

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

SYSTEM = """Eres un copywriter experto en carruseles de Instagram para una marca de \
bienestar y fitness. Escribes en español, con ganchos potentes, frases cortas y \
valor real en cada slide. No inventas datos médicos ni haces promesas de cura. \
Devuelves SIEMPRE un único objeto JSON válido, sin texto adicional."""


class CopyError(Exception):
    pass


def _headers() -> dict:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise CopyError("Falta ANTHROPIC_API_KEY en el entorno del backend.")
    return {
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def generate_copy(topic: str, slides: int = 6, tone: str = "",
                  extra: str = "", reference: str = "") -> dict:
    """
    Devuelve:
    {
      "topic": "...",
      "hook": "texto del slide 1 (portada)",
      "slides": [{"title": "...", "body": "..."}, ...],   # incluye la portada
      "caption": "texto del post para redes",
      "hashtags": ["#...", ...],
      "image_briefs": ["descripción visual para la imagen de cada slide", ...]
    }
    """
    brand = brand_mod.get_brand()
    n = max(3, min(int(slides), 10))

    ref_block = ""
    if reference:
        ref_block = (
            "\n\nRECREAR DESDE REFERENCIA: abajo va un carrusel/idea de otra persona que "
            "le gustó al cliente. Toma su ÁNGULO y ESTRUCTURA como inspiración, pero "
            "reescríbelo por completo en el estilo de la marca de arriba (voz, tono, temas). "
            "No copies frases textuales; hazlo propio.\n---\n" + reference + "\n---"
        )

    user = f"""PERFIL DE MARCA (respétalo estrictamente):
{brand}

Tema del carrusel: "{topic}"
Tono: {tone or 'motivador y cercano'}
{('Notas: ' + extra) if extra else ''}{ref_block}

Crea un carrusel de exactamente {n} slides (incluida la portada), fiel a la voz y los
temas de la marca.
Devuelve SOLO este JSON:
{{
  "topic": "{topic}",
  "hook": "titular de portada, potente y corto",
  "slides": [
    {{"title": "título corto del slide", "body": "1-2 frases de valor"}}
  ],
  "caption": "texto para el pie del post (2-5 líneas) con llamada a la acción",
  "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
  "image_briefs": ["descripción visual concreta para la imagen de fondo de cada slide (mismo orden y cantidad que slides)"]
}}
El array "slides" debe tener {n} elementos y "image_briefs" también {n}."""

    payload = {
        "model": DEFAULT_MODEL,
        "max_tokens": 2000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
    r = requests.post(ANTHROPIC_URL, headers=_headers(), json=payload, timeout=60)
    if r.status_code >= 400:
        raise CopyError(f"Anthropic {r.status_code}: {r.text[:500]}")
    data = r.json()
    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    ).strip()
    # Extraer el JSON aunque venga con ```json ... ```
    text = text.strip("`").replace("json\n", "", 1) if text.startswith("`") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise CopyError(f"Copy sin JSON: {text[:300]}")
    blob = text[start:end + 1]
    # strict=False permite saltos de línea/control chars dentro de los strings,
    # que Claude a veces incluye (p.ej. en caption multilínea).
    try:
        parsed = json.loads(blob, strict=False)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", blob)  # comas colgantes
        try:
            parsed = json.loads(cleaned, strict=False)
        except json.JSONDecodeError as e:
            raise CopyError(f"JSON de copy inválido: {e}") from e
    return parsed
