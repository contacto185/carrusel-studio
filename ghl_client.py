"""
Conector con GoHighLevel (LeadConnector) — Social Planner.

Usa un Private Integration Token (PIT) de la sub-cuenta Flowback Fitness.
Documentación: https://marketplace.gohighlevel.com/docs/ghl/social-planner

Variables de entorno:
  GHL_PIT         = pit-xxxxxxxx...   (token de integración privada)
  GHL_LOCATION_ID = vO5OEozodrPXZ8gRugCP  (sub-cuenta Flowback Fitness)
  GHL_API_VERSION = 2021-07-28 (por defecto)
"""
from __future__ import annotations

import os
import requests

BASE = "https://services.leadconnectorhq.com"


class GHLError(Exception):
    pass


def _headers() -> dict:
    pit = os.getenv("GHL_PIT", "").strip()
    if not pit:
        raise GHLError("Falta GHL_PIT (Private Integration Token) en el entorno.")
    return {
        "Authorization": f"Bearer {pit}",
        "Version": os.getenv("GHL_API_VERSION", "2021-07-28"),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _location_id() -> str:
    loc = os.getenv("GHL_LOCATION_ID", "").strip()
    if not loc:
        raise GHLError("Falta GHL_LOCATION_ID en el entorno.")
    return loc


def list_accounts() -> list[dict]:
    """Devuelve las cuentas sociales conectadas: [{id, name, platform, avatar}]."""
    loc = _location_id()
    url = f"{BASE}/social-media-posting/{loc}/accounts"
    r = requests.get(url, headers=_headers(), timeout=30)
    if r.status_code >= 400:
        raise GHLError(f"GHL accounts {r.status_code}: {r.text[:400]}")
    data = r.json()
    # La forma de la respuesta puede venir como {results:{accounts:[...]}} o {accounts:[...]}
    accounts = (
        data.get("accounts")
        or (data.get("results") or {}).get("accounts")
        or []
    )
    out = []
    for a in accounts:
        out.append({
            "id": a.get("id") or a.get("_id"),
            "name": a.get("name") or a.get("username") or "",
            "platform": a.get("platform") or a.get("type") or "",
            "avatar": a.get("avatar") or a.get("profilePicture") or "",
        })
    return out


def list_users() -> list[dict]:
    """Lista los usuarios de la sub-cuenta (para obtener un userId válido)."""
    loc = _location_id()
    url = f"{BASE}/users/"
    r = requests.get(url, headers=_headers(), params={"locationId": loc}, timeout=30)
    if r.status_code >= 400:
        raise GHLError(f"GHL users {r.status_code}: {r.text[:400]}")
    data = r.json()
    users = data.get("users") or (data.get("results") or {}).get("users") or []
    return [{"id": u.get("id") or u.get("_id"),
             "name": (u.get("name") or f"{u.get('firstName','')} {u.get('lastName','')}").strip(),
             "email": u.get("email", "")} for u in users]


def _user_id() -> str:
    uid = os.getenv("GHL_USER_ID", "").strip()
    if uid:
        return uid
    # fallback: primer usuario de la sub-cuenta
    users = list_users()
    if not users:
        raise GHLError("No hay GHL_USER_ID configurado y no pude listar usuarios.")
    return users[0]["id"]


def create_draft(account_ids: list[str], caption: str, media_urls: list[str],
                 schedule_date: str | None = None, user_id: str | None = None) -> dict:
    """
    Crea un post en el Social Planner con status=draft.

    account_ids : IDs de las cuentas sociales destino (de list_accounts()).
    caption     : texto/copy del post.
    media_urls  : URLs públicas de las imágenes del carrusel (en orden).
    schedule_date: ISO opcional (si quieres pre-agendar el borrador).

    Devuelve el JSON del post creado.
    """
    if not account_ids:
        raise GHLError("Debes indicar al menos una cuenta social destino.")
    loc = _location_id()
    url = f"{BASE}/social-media-posting/{loc}/posts"

    media = [{"url": u} for u in media_urls]
    body: dict = {
        "accountIds": account_ids,
        "summary": caption,
        "media": media,
        "status": "draft",
        "type": "post",
        "userId": user_id or _user_id(),
    }
    if schedule_date:
        body["scheduleDate"] = schedule_date

    r = requests.post(url, headers=_headers(), json=body, timeout=45)
    if r.status_code >= 400:
        raise GHLError(f"GHL create draft {r.status_code}: {r.text[:600]}")
    return r.json()
