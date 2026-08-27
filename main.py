"""
Carrusel Studio — Backend (FastAPI)

Orquesta: copy (Claude) + imágenes (Lovart) + borradores (GoHighLevel).

Protección simple por clave de acceso: el frontend envía el header
  X-App-Key: <APP_ACCESS_KEY>
en cada request. Es una herramienta interna, no un SaaS multiusuario.

Endpoints principales:
  GET  /health
  GET  /api/ghl/accounts                 -> cuentas sociales conectadas
  POST /api/copy                         -> genera copy de un carrusel
  POST /api/lovart/generate              -> genera 1 imagen
  POST /api/carousel/generate            -> copy + imágenes de UN carrusel
  POST /api/carousel/batch               -> varios carruseles de una lista de temas
  POST /api/ghl/draft                    -> crea borrador en el Social Planner
  POST /api/lovart/confirm               -> confirma generación de alto costo
"""
from __future__ import annotations

import os
from typing import Optional

import tempfile

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path as _Path

import lovart_client
import ghl_client
import copy_client
import brand as brand_mod
import ratelimit
import refs_store
import ig_client

app = FastAPI(title="Carrusel Studio Backend", version="1.0.0")

# CORS: en producción restringe allow_origins a tu dominio del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_key(x_app_key: Optional[str]):
    expected = os.getenv("APP_ACCESS_KEY", "").strip()
    if not expected:
        return  # sin clave configurada = abierto (solo para pruebas locales)
    if (x_app_key or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Clave de acceso inválida.")


# ---------- Modelos de request ----------
class CopyReq(BaseModel):
    topic: str
    slides: int = 6
    tone: str = ""
    extra: str = ""
    reference: str = ""


class ImageReq(BaseModel):
    prompt: str
    model: Optional[str] = None
    project_id: Optional[str] = None
    thread_id: Optional[str] = None
    attachments: Optional[list[str]] = None


class CarouselReq(BaseModel):
    topic: str
    slides: int = 6
    tone: str = ""
    model: Optional[str] = None


class BatchReq(BaseModel):
    topics: list[str]
    slides: int = 6
    tone: str = ""
    model: Optional[str] = None


class DraftReq(BaseModel):
    accountIds: list[str]
    caption: str
    mediaUrls: list[str]
    scheduleDate: Optional[str] = None


class ConfirmReq(BaseModel):
    thread_id: str


# ---------- Endpoints ----------
@app.get("/health")
def health():
    return {"ok": True, "service": "carrusel-studio-backend"}


@app.get("/")
def root():
    """Sirve la app (index.html) desde el mismo backend, para entrar por link sin abrir archivos."""
    idx = _Path(__file__).parent / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return {"ok": True, "service": "carrusel-studio-backend", "app": "index.html no encontrado"}


@app.get("/api/ghl/accounts")
def ghl_accounts(x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        return {"accounts": ghl_client.list_accounts()}
    except ghl_client.GHLError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/copy")
def api_copy(req: CopyReq, request: Request, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    ratelimit.check_budget("copy")
    try:
        return copy_client.generate_copy(req.topic, req.slides, req.tone, req.extra,
                                         reference=req.reference)
    except copy_client.CopyError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/lovart/generate")
def api_image(req: ImageReq, request: Request, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    ratelimit.check_budget("img")
    try:
        return lovart_client.generate_image(
            req.prompt, req.model, req.project_id, req.thread_id, req.attachments
        )
    except lovart_client.LovartError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------- Leer un carrusel de Instagram (link + capturas) ----------
class LinkReq(BaseModel):
    url: str


@app.post("/api/ig/read")
def api_ig_read(req: LinkReq, request: Request, x_app_key: Optional[str] = Header(default=None)):
    """Intenta leer el caption/descripción pública de un post de Instagram u otro link."""
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    try:
        return ig_client.read_link(req.url)
    except ig_client.IGError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/ig/read-images")
async def api_ig_read_images(request: Request,
                             files: list[UploadFile] = File(...),
                             x_app_key: Optional[str] = Header(default=None)):
    """Lee capturas del carrusel con visión (Claude) y devuelve el texto de cada slide."""
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    ratelimit.check_budget("copy")
    try:
        images = []
        for f in files:
            raw = await f.read()
            mt = f.content_type or "image/png"
            if mt not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
                mt = "image/png"
            images.append((mt, raw))
        return ig_client.read_images(images)
    except ig_client.IGError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/usage")
def api_usage(x_app_key: Optional[str] = Header(default=None)):
    """Uso del día (protección de créditos): imágenes y copys generados."""
    _check_key(x_app_key)
    return ratelimit.stats()


@app.post("/api/lovart/confirm")
def api_confirm(req: ConfirmReq, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        return lovart_client.confirm(req.thread_id)
    except lovart_client.LovartError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _build_carousel(topic: str, slides: int, tone: str, model: Optional[str],
                    reference: str = "", attachments: Optional[list[str]] = None) -> dict:
    """Genera el copy y una imagen por slide. Devuelve el carrusel completo."""
    ratelimit.check_budget("copy")
    copy = copy_client.generate_copy(topic, slides, tone, reference=reference)
    briefs = copy.get("image_briefs") or []
    slide_texts = copy.get("slides") or []
    style = brand_mod.visual_style()
    built = []
    for i, slide in enumerate(slide_texts):
        brief = briefs[i] if i < len(briefs) else slide.get("title", topic)
        prompt = (
            f"{brief}. ESTILO VISUAL DE LA MARCA: {style}. "
            f"Coherente para un carrusel de Instagram sobre '{topic}'. "
            f"Sin ningún texto ni letras en la imagen."
        )
        try:
            ratelimit.check_budget("img")
            img = lovart_client.generate_image(prompt, model, attachments=attachments)
            image_url = img["image_urls"][0] if img.get("image_urls") else None
            warning = img.get("warning")
        except lovart_client.LovartError as e:
            image_url, warning = None, str(e)
        built.append({
            "index": i,
            "title": slide.get("title", ""),
            "body": slide.get("body", ""),
            "image_url": image_url,
            "warning": warning,
        })
    return {
        "topic": topic,
        "hook": copy.get("hook", ""),
        "caption": copy.get("caption", ""),
        "hashtags": copy.get("hashtags", []),
        "slides": built,
    }


@app.post("/api/carousel/generate")
def api_carousel(req: CarouselReq, request: Request, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    try:
        return _build_carousel(req.topic, req.slides, req.tone, req.model)
    except (copy_client.CopyError, lovart_client.LovartError) as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/carousel/batch")
def api_batch(req: BatchReq, request: Request, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    results = []
    for topic in req.topics:
        try:
            results.append(_build_carousel(topic, req.slides, req.tone, req.model))
        except Exception as e:  # noqa: BLE001 - un tema que falle no debe tumbar el lote
            results.append({"topic": topic, "error": str(e), "slides": []})
    return {"carousels": results}


@app.post("/api/ghl/draft")
def api_draft(req: DraftReq, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        post = ghl_client.create_draft(
            req.accountIds, req.caption, req.mediaUrls, req.scheduleDate
        )
        return {"ok": True, "post": post}
    except ghl_client.GHLError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------- Marca / estilo ----------
class BrandReq(BaseModel):
    brand: str


@app.get("/api/brand")
def api_get_brand(x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    return {"brand": brand_mod.get_brand()}


@app.put("/api/brand")
def api_put_brand(req: BrandReq, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    brand_mod.save_brand(req.brand)
    return {"ok": True}


# ---------- Referencias (swipe file) — almacén COMPARTIDO (Upstash) ----------
class RefReq(BaseModel):
    url: str = ""
    notes: str = ""
    text: str = ""
    images: Optional[list[str]] = None


class RefUpdateReq(BaseModel):
    notes: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None
    images: Optional[list[str]] = None


class BulkRefsReq(BaseModel):
    references: list[RefReq]
    mode: str = "if_empty"   # if_empty | merge | replace


@app.get("/api/references")
def api_get_refs(x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        return {"references": refs_store.list_all(), "shared": refs_store.upstash_enabled()}
    except refs_store.RefsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/references")
def api_add_ref(req: RefReq, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        return {"reference": refs_store.add(req.model_dump())}
    except refs_store.RefsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.put("/api/references/{ref_id}")
def api_update_ref(ref_id: int, req: RefUpdateReq, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        ref = refs_store.update(ref_id, req.model_dump(exclude_none=True))
        if ref is None:
            raise HTTPException(status_code=404, detail="Referencia no encontrada.")
        return {"reference": ref}
    except refs_store.RefsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/references/bulk")
def api_bulk_refs(req: BulkRefsReq, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        items = [r.model_dump() for r in req.references]
        return refs_store.bulk_seed(items, mode=req.mode if req.mode in ("if_empty", "merge", "replace") else "if_empty")
    except refs_store.RefsError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/lovart/upload")
async def api_upload(request: Request, file: UploadFile = File(...), x_app_key: Optional[str] = Header(default=None)):
    """Sube una imagen (ej. foto de Jimmy/Kira) a Lovart y devuelve su URL para usar de referencia."""
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    try:
        suffix = _Path(file.filename or "img.png").suffix or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            path = tmp.name
        url = lovart_client.upload_file(path)
        return {"url": url}
    except lovart_client.LovartError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.delete("/api/references/{ref_id}")
def api_del_ref(ref_id: int, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    try:
        refs_store.delete(ref_id)
        return {"ok": True}
    except refs_store.RefsError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------- Recrear desde una referencia (link que le gustó) ----------
class RecreateReq(BaseModel):
    url: str = ""
    notes: str = ""
    text: str = ""
    topic: str = ""
    slides: int = 6
    tone: str = ""
    model: Optional[str] = None


@app.post("/api/carousel/recreate")
def api_recreate(req: RecreateReq, request: Request, x_app_key: Optional[str] = Header(default=None)):
    _check_key(x_app_key)
    ratelimit.check_ip(request)
    reference = (f"URL de referencia: {req.url}\n"
                 f"Qué me gusta / notas: {req.notes}\n"
                 f"Texto de los slides (si se pegó):\n{req.text}").strip()
    topic = req.topic or req.notes or "Idea inspirada en la referencia"
    try:
        return _build_carousel(topic, req.slides, req.tone, req.model, reference=reference)
    except (copy_client.CopyError, lovart_client.LovartError) as e:
        raise HTTPException(status_code=502, detail=str(e))
