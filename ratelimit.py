"""
Rate limiting simple en memoria para proteger los créditos de Lovart/Anthropic.

Como la clave de acceso viaja en el frontend (app estática), cualquiera que vea
la URL podría llamar al backend. Esto NO lo vuelve secreto, pero pone un techo
para que nadie pueda quemar tus créditos:

  1. Límite por IP y por minuto  -> frena a alguien martillando el backend.
  2. Presupuesto diario global    -> techo duro de operaciones caras al día.

Todo es configurable por variables de entorno (con defaults razonables):
  RL_PER_IP_PER_MIN        = 60     (requests caros por IP por minuto)
  RL_DAILY_IMAGES          = 800    (generaciones de imagen por día, global)
  RL_DAILY_COPY            = 300     (generaciones de copy por día, global)

Nota: es en memoria y por proceso. En el free tier de Render hay 1 worker, así
que funciona bien. Si algún día escalas a varios workers, esto se mueve a Redis.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from datetime import date

from fastapi import HTTPException, Request


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


PER_IP_PER_MIN = _int_env("RL_PER_IP_PER_MIN", 60)
DAILY_IMAGES = _int_env("RL_DAILY_IMAGES", 800)
DAILY_COPY = _int_env("RL_DAILY_COPY", 300)

# Estado en memoria.
_ip_hits: dict[str, deque] = defaultdict(deque)   # ip -> timestamps (últimos 60s)
_daily: dict[str, int] = defaultdict(int)         # "img:2026-08-25" -> conteo
_daily_day = {"d": date.today().isoformat()}


def _client_ip(request: Request) -> str:
    # Render/Proxies mandan la IP real en X-Forwarded-For.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _roll_day() -> None:
    today = date.today().isoformat()
    if _daily_day["d"] != today:
        _daily.clear()
        _daily_day["d"] = today


def check_ip(request: Request) -> None:
    """Frena a una IP que hace demasiados requests caros por minuto."""
    if PER_IP_PER_MIN <= 0:
        return
    ip = _client_ip(request)
    now = time.time()
    dq = _ip_hits[ip]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= PER_IP_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="Demasiadas solicitudes seguidas. Espera un momento e intenta de nuevo.",
        )
    dq.append(now)


def check_budget(kind: str) -> None:
    """Aplica el techo diario global. kind: 'img' o 'copy'."""
    _roll_day()
    limit = DAILY_IMAGES if kind == "img" else DAILY_COPY
    if limit <= 0:
        return
    key = f"{kind}:{_daily_day['d']}"
    if _daily[key] >= limit:
        raise HTTPException(
            status_code=429,
            detail=(f"Se alcanzó el límite diario de {'imágenes' if kind=='img' else 'copys'} "
                    f"({limit}). Es una protección de créditos; se reinicia mañana "
                    f"(o súbelo con la variable {'RL_DAILY_IMAGES' if kind=='img' else 'RL_DAILY_COPY'})."),
        )
    _daily[key] += 1


def stats() -> dict:
    _roll_day()
    d = _daily_day["d"]
    return {
        "day": d,
        "images_today": _daily.get(f"img:{d}", 0),
        "copy_today": _daily.get(f"copy:{d}", 0),
        "limits": {"images": DAILY_IMAGES, "copy": DAILY_COPY, "per_ip_per_min": PER_IP_PER_MIN},
    }
