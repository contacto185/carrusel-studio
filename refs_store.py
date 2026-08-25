"""
Almacén COMPARTIDO de referencias (swipe file).

Objetivo: que las referencias vivan en un solo lugar en la nube, para que:
  - aparezcan iguales en TODOS los equipos/navegadores, y
  - al renombrar o borrar una, el cambio se vea para todos.

Backend de persistencia:
  1. Upstash Redis (REST)  -> si están configuradas las variables de entorno:
       UPSTASH_REDIS_REST_URL   = https://xxx.upstash.io
       UPSTASH_REDIS_REST_TOKEN = token
     Persiste de verdad (sobrevive redeploys y a que el server de Render "duerma").
  2. Archivo local (fallback) -> si Upstash no está configurado. Sirve para probar,
     pero en Render (disco efímero) se reinicia cuando el server duerme. Por eso,
     para uso real, hay que configurar Upstash.

Se guarda TODO el arreglo de referencias como un solo JSON bajo la clave 'cs_refs'.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import requests

KEY = "cs_refs"
_LOCK = threading.Lock()

DATA = Path(__file__).parent / "data"
DATA.mkdir(exist_ok=True)
FILE = DATA / "references.json"


def _upstash_cfg() -> tuple[str, str]:
    url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip().rstrip("/")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
    return url, token


def upstash_enabled() -> bool:
    url, token = _upstash_cfg()
    return bool(url and token)


class RefsError(Exception):
    pass


def _upstash(cmd: list) -> object:
    """Ejecuta un comando Redis vía la REST API de Upstash. cmd = ['GET','cs_refs'] etc."""
    url, token = _upstash_cfg()
    if not url or not token:
        raise RefsError("Upstash no configurado.")
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json=cmd, timeout=15)
    if r.status_code >= 400:
        raise RefsError(f"Upstash {r.status_code}: {r.text[:300]}")
    return r.json().get("result")


# ---------- lectura / escritura del arreglo completo ----------
def _read_all() -> list[dict]:
    if upstash_enabled():
        raw = _upstash(["GET", KEY])
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    # fallback archivo
    if FILE.exists():
        try:
            return json.loads(FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _write_all(refs: list[dict]) -> None:
    payload = json.dumps(refs, ensure_ascii=False)
    if upstash_enabled():
        _upstash(["SET", KEY, payload])
    else:
        FILE.write_text(payload, encoding="utf-8")


def _next_id(refs: list[dict]) -> int:
    return max([int(r.get("id", 0) or 0) for r in refs], default=0) + 1


def _clean(ref: dict, rid: int) -> dict:
    return {
        "id": rid,
        "url": ref.get("url", "") or "",
        "notes": ref.get("notes", "") or "",
        "text": ref.get("text", "") or "",
        "images": ref.get("images", []) or [],
    }


# ---------- API pública ----------
def list_all() -> list[dict]:
    with _LOCK:
        return _read_all()


def add(ref: dict) -> dict:
    with _LOCK:
        refs = _read_all()
        new = _clean(ref, _next_id(refs))
        refs.append(new)
        _write_all(refs)
        return new


def update(ref_id: int, fields: dict) -> dict | None:
    with _LOCK:
        refs = _read_all()
        out = None
        for r in refs:
            if str(r.get("id")) == str(ref_id):
                for k in ("notes", "url", "text", "images"):
                    if k in fields and fields[k] is not None:
                        r[k] = fields[k]
                out = r
                break
        if out is not None:
            _write_all(refs)
        return out


def delete(ref_id: int) -> None:
    with _LOCK:
        refs = [r for r in _read_all() if str(r.get("id")) != str(ref_id)]
        _write_all(refs)


def bulk_seed(items: list[dict], mode: str = "if_empty") -> dict:
    """
    Carga inicial / importación.
      mode='if_empty' : solo si el store está vacío (siembra desde un navegador).
      mode='merge'    : agrega los que no existan (por primera imagen o nombre).
      mode='replace'  : reemplaza todo.
    """
    with _LOCK:
        cur = _read_all()
        if mode == "if_empty" and cur:
            return {"seeded": 0, "total": len(cur), "skipped": "no vacío"}
        if mode == "replace":
            refs = []
        else:
            refs = list(cur)
        seen = set()
        for r in refs:
            k = (r.get("images") or [""])[0] or r.get("notes", "")
            seen.add(k)
        added = 0
        for it in items:
            k = (it.get("images") or [""])[0] or it.get("notes", "")
            if k in seen:
                continue
            seen.add(k)
            refs.append(_clean(it, _next_id(refs)))
            added += 1
        _write_all(refs)
        return {"seeded": added, "total": len(refs)}
