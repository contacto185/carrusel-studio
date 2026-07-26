"""
Generación automática diaria de carruseles → borradores en GoHighLevel.

Pensado para correr una vez al día (ej. 9:00 AM Chile) desde un Cron Job
(Render Cron, GitHub Actions, cron del sistema, etc.).

Qué hace:
  1. Lee topics.json (calendario de temas).
  2. Elige los temas del día (rotando la lista según el día del año).
  3. Genera el/los carrusel(es): copy + imágenes con Lovart.
  4. Crea un BORRADOR en el Social Planner de GHL con las cuentas por defecto
     (GHL_DEFAULT_ACCOUNT_IDS). Tú luego revisas y publicas desde GHL.

Uso:
  python3 scheduler.py           # corre la tanda del día
  python3 scheduler.py --dry     # genera pero NO crea borradores (prueba)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import ghl_client
from main import _build_carousel

TOPICS_FILE = Path(__file__).parent / "topics.json"


def todays_topics(cfg: dict) -> list[str]:
    topics = cfg.get("topics", [])
    per_day = int(cfg.get("per_day", 1))
    if not topics:
        return []
    # Rotación determinística por día del año.
    doy = date.today().timetuple().tm_yday
    start = (doy * per_day) % len(topics)
    return [topics[(start + i) % len(topics)] for i in range(per_day)]


def main():
    dry = "--dry" in sys.argv
    cfg = json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    topics = todays_topics(cfg)
    if not topics:
        print("No hay temas configurados en topics.json")
        return

    account_ids = [
        a.strip() for a in os.getenv("GHL_DEFAULT_ACCOUNT_IDS", "").split(",")
        if a.strip()
    ]
    slides = int(cfg.get("slides", 6))
    tone = cfg.get("tone", "")

    for topic in topics:
        print(f"\n=== Generando carrusel: {topic} ===")
        carousel = _build_carousel(topic, slides, tone, None)
        media = [s["image_url"] for s in carousel["slides"] if s.get("image_url")]
        caption = carousel["caption"]
        tags = " ".join(carousel.get("hashtags", []))
        full_caption = f"{caption}\n\n{tags}".strip()
        print(f"  Slides con imagen: {len(media)}/{len(carousel['slides'])}")

        if dry:
            print("  [DRY] No se crea borrador. Caption:\n", full_caption[:300])
            continue
        if not account_ids:
            print("  ⚠ Sin GHL_DEFAULT_ACCOUNT_IDS: no se crea borrador.")
            continue
        if not media:
            print("  ⚠ Sin imágenes generadas: no se crea borrador.")
            continue

        post = ghl_client.create_draft(account_ids, full_caption, media)
        print(f"  ✓ Borrador creado en GHL: {json.dumps(post)[:200]}")


if __name__ == "__main__":
    main()
