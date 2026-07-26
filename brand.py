"""
Perfil de marca "Estilo Jimmy" + banco de referencias (swipe file).

El perfil se inyecta en la generación de copy y en los prompts de imagen para que
el contenido salga con la línea de Jimmy / Flowback y NO al azar.

Se guarda en data/brand.md y data/references.json (editable desde la app).
Nota: en hosting con disco efímero (ej. Render), las ediciones persisten hasta el
próximo redeploy. Para persistencia total conviene una base de datos (v2).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)
BRAND_FILE = DATA / "brand.md"
REFS_FILE = DATA / "references.json"

DEFAULT_BRAND = """# Estilo Jimmy — Flowback

## Marca
Jimmy Lavín, entrenador psicocorporal (junto a Kira). Flowback / Flowback Fitness.
Bienestar integral cuerpo–mente: músculo, movimiento, desinflamación, alimentación
sin culpa, manejo del estrés y la ansiedad, hábitos sostenibles. Entrenamiento por
Zoom desde casa. Chile, español cercano.

## Voz y tono
- Cálido, cercano, motivador. Sin culpa ni castigo.
- Pro-placer: "comer rico", "sin dietas de castigo", "sin quitarte el placer de la mesa".
- Holístico: lo que pones en el plato le habla a tu digestión, tu energía y tu ánimo.
- Educa con datos simples y accionables; nunca promesas médicas milagrosas.
- Frases cortas, directas, con ritmo. Segunda persona ("tú").
- Firma habitual: "Con amor y Mucho Flow — Kira & Jimmy".
- Emojis con medida: ❤️ 🐌 👇 💪 🌿. CTA típico: "Comenta 'yo quiero' y te llega el link al DM".

## Temas pilares
Desinflamación / comer rico antiinflamatorio · Músculo y proteína · Movimiento y
movilidad · Ansiedad, estrés y descanso · Bienestar psicocorporal · Hábitos sostenibles.

## Estilo visual (para las imágenes)
Dos líneas coherentes:
1. Editorial cálido: fotografía real (luz natural, tonos tierra/dorados, madera, comida
   real, naturaleza), con aire y estética premium.
2. Infográfico potente: fondos fotográficos, datos destacados (calorías, gramos, números
   grandes), acentos cálidos.
Siempre se ve real y humano (a menudo aparece Jimmy), nada de stock frío.
IMPORTANTE: la imagen va SIN texto incrustado — el texto lo pone la app encima.

## Estructura del carrusel
- Slide 1: gancho potente (pregunta o dato que frena el scroll).
- Slides intermedios: un punto de valor concreto y accionable por slide.
- Último slide: cierre + CTA (comenta / guarda / DM).

## Reglas
- Nunca prometer curas ni resultados médicos garantizados.
- Nada de dietas de castigo ni culpa; siempre desde el disfrute y la sostenibilidad.
- Español de Chile neutro y cercano.
"""


def get_brand() -> str:
    if BRAND_FILE.exists():
        return BRAND_FILE.read_text(encoding="utf-8")
    BRAND_FILE.write_text(DEFAULT_BRAND, encoding="utf-8")
    return DEFAULT_BRAND


def save_brand(text: str) -> None:
    BRAND_FILE.write_text(text or "", encoding="utf-8")


def visual_style() -> str:
    """Extrae la sección de estilo visual para anteponer a los prompts de imagen."""
    brand = get_brand()
    marker = "## Estilo visual"
    if marker in brand:
        seg = brand.split(marker, 1)[1]
        seg = seg.split("\n##", 1)[0]
        return seg.strip()
    return ("Fotografía real, cálida y premium; luz natural, tonos tierra/dorados; "
            "humano y cercano; sin texto incrustado.")


def list_references() -> list[dict]:
    if REFS_FILE.exists():
        try:
            return json.loads(REFS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def add_reference(url: str, notes: str = "", text: str = "") -> dict:
    refs = list_references()
    ref = {"id": (max([r.get("id", 0) for r in refs], default=0) + 1),
           "url": url, "notes": notes, "text": text}
    refs.append(ref)
    REFS_FILE.write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")
    return ref


def delete_reference(ref_id: int) -> None:
    refs = [r for r in list_references() if r.get("id") != ref_id]
    REFS_FILE.write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")
