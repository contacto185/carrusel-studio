"""
Conector con Lovart usando el cliente oficial (MIT) vendido en vendor/agent_skill.py.

En vez de reimplementar la firma HMAC-SHA256 de Lovart (que puede cambiar y romperse),
llamamos al cliente oficial como subproceso: es el camino soportado y estable.

Requiere las variables de entorno:
  LOVART_ACCESS_KEY = ak_xxx
  LOVART_SECRET_KEY = sk_xxx
Opcional:
  LOVART_PROJECT_ID = id del proyecto/canvas de Lovart donde agrupar el contenido
  LOVART_IMAGE_MODEL = tool de modelo por defecto (ej: generate_image_seedream_v5_pro)
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

# Ruta al cliente oficial de Lovart. Soporta ambos layouts:
#  - despliegue plano (agent_skill.py junto a este archivo)
#  - local con vendor/ (agent_skill.py dentro de vendor/)
_AS_ROOT = Path(__file__).parent / "agent_skill.py"
_AS_VENDOR = Path(__file__).parent / "vendor" / "agent_skill.py"
AGENT_SKILL = str(_AS_ROOT if _AS_ROOT.exists() else _AS_VENDOR)

# Modelo de imagen por defecto. Ver la tabla completa en vendor/LOVART_SKILL.md.
DEFAULT_IMAGE_MODEL = os.getenv("LOVART_IMAGE_MODEL", "generate_image_seedream_v5_pro")

# Timeout generoso: la generación puede tardar.
GEN_TIMEOUT_SEC = int(os.getenv("LOVART_TIMEOUT", "240"))


class LovartError(Exception):
    pass


def _env() -> dict:
    ak = os.getenv("LOVART_ACCESS_KEY", "").strip()
    sk = os.getenv("LOVART_SECRET_KEY", "").strip()
    if not ak or not sk:
        raise LovartError(
            "Faltan LOVART_ACCESS_KEY y/o LOVART_SECRET_KEY en el entorno del backend."
        )
    env = dict(os.environ)
    env["LOVART_ACCESS_KEY"] = ak
    env["LOVART_SECRET_KEY"] = sk
    return env


def _run(args: list[str], timeout: int = GEN_TIMEOUT_SEC) -> dict:
    """Ejecuta agent_skill.py y devuelve el JSON de stdout."""
    cmd = ["python3", AGENT_SKILL, *args]
    try:
        proc = subprocess.run(
            cmd,
            env=_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise LovartError(f"Lovart tardó demasiado (> {timeout}s).") from e

    if proc.returncode != 0:
        # El cliente imprime errores legibles en stderr/stdout.
        detail = (proc.stderr or proc.stdout or "").strip()
        raise LovartError(f"Lovart falló: {detail[:600]}")

    out = (proc.stdout or "").strip()
    # El comando puede emitir líneas de log antes del JSON: tomar el último bloque JSON.
    try:
        # buscar la primera '{' de la última línea JSON válida
        start = out.rfind("\n{")
        candidate = out[start + 1:] if start != -1 else out
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise LovartError(f"Respuesta no-JSON de Lovart: {out[:400]}") from e


def _extract_image_urls(result: dict) -> list[str]:
    """Saca las URLs de imagen del formato de salida del cliente (items[].artifacts[])."""
    urls: list[str] = []
    for item in result.get("items", []):
        for art in item.get("artifacts", []) or []:
            if art.get("type") == "image" and art.get("content"):
                urls.append(art["content"])
    # fallback: campo downloaded[]
    if not urls:
        for d in result.get("downloaded", []) or []:
            if d.get("type") == "image" and d.get("url"):
                urls.append(d["url"])
    return urls


def upload_file(local_path: str) -> str:
    """Sube una imagen local a Lovart y devuelve su URL de CDN (para usar como referencia)."""
    result = _run(["upload", "--file", local_path], timeout=120)
    return result.get("url", "")


def generate_image(prompt: str, model: str | None = None,
                   project_id: str | None = None,
                   thread_id: str | None = None,
                   attachments: list[str] | None = None) -> dict:
    """
    Genera una imagen a partir de un prompt.

    attachments: URLs de imágenes de referencia (estilo/sujeto, p.ej. fotos de Jimmy/Kira).
    thread_id: si se pasa, continúa la conversación para EDITAR la imagen anterior.

    Devuelve: {"image_urls": [...], "thread_id": "...", "project_id": "...",
               "agent_message": "...", "ok": bool, "warning": str|None}
    """
    project_id = project_id or os.getenv("LOVART_PROJECT_ID", "").strip() or None
    model = model or DEFAULT_IMAGE_MODEL

    args = ["chat", "--prompt", prompt, "--json"]
    if project_id:
        args += ["--project-id", project_id]
    if thread_id:
        args += ["--thread-id", thread_id]
    if model:
        args += ["--prefer-models", json.dumps({"IMAGE": [model]})]
    if attachments:
        args += ["--attachments", *attachments]

    result = _run(args)

    final_status = result.get("final_status") or result.get("status")
    if final_status == "pending_confirmation":
        # Modelo de alto costo pidió confirmación. En este backend no auto-confirmamos
        # generación cara sin control; el frontend puede exponer un botón para confirmar.
        return {
            "image_urls": [],
            "thread_id": result.get("thread_id"),
            "project_id": result.get("project_id"),
            "ok": False,
            "warning": "pending_confirmation",
            "agent_message": "Este modelo requiere confirmación (alto costo).",
        }

    urls = _extract_image_urls(result)
    # Al editar (continuar un thread) el resultado trae [imagen_vieja, ..., imagen_nueva];
    # devolvemos la más NUEVA primero para que image_urls[0] sea siempre la última generada.
    urls = urls[::-1]
    ok = bool(urls) and result.get("generation_succeeded", True) is not False
    return {
        "image_urls": urls,
        "thread_id": result.get("thread_id"),
        "project_id": result.get("project_id"),
        "ok": ok,
        "warning": result.get("warning"),
        "agent_message": result.get("agent_message") or _first_text(result),
    }


def _first_text(result: dict) -> str:
    for item in result.get("items", []):
        if item.get("type") == "assistant" and item.get("text"):
            return item["text"]
    return ""


def confirm(thread_id: str) -> dict:
    """Confirma una operación de alto costo pendiente y espera el resultado."""
    result = _run(["confirm", "--thread-id", thread_id, "--json"])
    urls = _extract_image_urls(result)
    return {
        "image_urls": urls,
        "thread_id": thread_id,
        "ok": bool(urls),
    }
