# Carrusel Studio — Backend

Genera carruseles (copy con Claude + imágenes con Lovart) y los deja como
**borradores** en el Social Planner de GoHighLevel. Incluye un generador
automático diario a partir de un calendario de temas.

## Arquitectura

```
Frontend (app web)  ──►  Backend FastAPI  ──►  Lovart (cliente oficial, imágenes)
                                          ──►  Claude/Anthropic (copy)
                                          ──►  GoHighLevel (borradores + cuentas)
   Cron diario 9am  ──►  scheduler.py  ──►  (mismos conectores)
```

El backend guarda TODAS las llaves (nunca van al navegador). El frontend solo
manda el header `X-App-Key`.

## Archivos

| Archivo | Qué hace |
|---|---|
| `main.py` | API FastAPI (endpoints). |
| `lovart_client.py` | Envuelve el cliente oficial de Lovart (`vendor/agent_skill.py`). |
| `ghl_client.py` | GoHighLevel Social Planner (listar cuentas + crear borrador). |
| `copy_client.py` | Copy del carrusel con Claude. |
| `scheduler.py` | Generación automática diaria → borradores en GHL. |
| `topics.json` | Calendario de temas (desinflamación, movimiento, salud…). |
| `vendor/agent_skill.py` | Cliente oficial de Lovart (MIT, sin cambios). |

## Llaves que necesitas (todo va en variables de entorno)

1. **Lovart** — `LOVART_ACCESS_KEY` (ak_…) y `LOVART_SECRET_KEY` (sk_…).
   En Lovart.ai → ícono de perfil (arriba a la derecha) → ajustes → API.
   Copia **ambas**: la app necesita el `sk_` además del `ak_`.
2. **GoHighLevel** — `GHL_PIT` (Private Integration Token de la sub-cuenta
   Flowback Fitness) y `GHL_LOCATION_ID` (ya la tenemos: `vO5OEozodrPXZ8gRugCP`).
   El token se ve **una sola vez** al crearlo; si lo perdiste, se crea/rota en
   Ajustes → Integraciones privadas de esa sub-cuenta. Necesita permisos de
   **Social Planner** (lectura y escritura).
3. **Claude** — `ANTHROPIC_API_KEY` (sk-ant-…). Ajusta `ANTHROPIC_MODEL` si el id cambia.
4. **App** — `APP_ACCESS_KEY`: invéntate una clave larga; el frontend la usa.

## Correr en local

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y rellena tus llaves
set -a && source .env && set +a
uvicorn main:app --reload --port 8000
```

Prueba:
```bash
curl -H "X-App-Key: $APP_ACCESS_KEY" http://localhost:8000/api/ghl/accounts
```

## Desplegar (recomendado: Render)

1. Sube esta carpeta a un repo de git.
2. En Render → New → Blueprint, apunta a `render.yaml`.
3. Crea las variables marcadas `sync: false` (las llaves) en el dashboard.
4. El servicio web queda en `https://<tu-servicio>.onrender.com`.
5. El Cron Job `carrusel-studio-daily` corre a las 13:00 UTC (= 9:00 AM Chile).

## Endpoints

| Método | Ruta | Cuerpo | Devuelve |
|---|---|---|---|
| GET | `/health` | — | estado |
| GET | `/api/ghl/accounts` | — | cuentas sociales conectadas |
| POST | `/api/copy` | `{topic, slides, tone}` | copy del carrusel |
| POST | `/api/lovart/generate` | `{prompt, model?}` | `{image_urls, ...}` |
| POST | `/api/carousel/generate` | `{topic, slides, tone, model?}` | carrusel completo |
| POST | `/api/carousel/batch` | `{topics:[...], slides, tone}` | varios carruseles |
| POST | `/api/ghl/draft` | `{accountIds:[...], caption, mediaUrls:[...]}` | borrador creado |
| GET/PUT | `/api/brand` | `{brand}` | ver/editar el perfil “Estilo Jimmy” |
| GET/POST | `/api/references` | `{url, notes, text}` | banco de referencias (swipe file) |
| POST | `/api/carousel/recreate` | `{url, notes, text, topic, slides}` | recrear un carrusel de referencia a tu estilo |

Todos (menos `/health`) requieren el header `X-App-Key`.

## Estilo de marca (que no salga al azar)

`brand.py` guarda el perfil **“Estilo Jimmy”** (`data/brand.md`) — voz, tono, temas,
estilo visual y estructura, extraído de tu contenido real (Instagram + Lovart). Ese
perfil se inyecta en **cada** generación: el copy respeta tu voz y las imágenes usan tu
estilo visual. Lo editas desde la pestaña **Estilo & Ref** de la app.

El modo **Recrear** toma un carrusel que te gustó (link + notas + texto opcional) y crea
uno nuevo con el mismo ángulo pero en tu estilo — no lo copia.

`GHL_USER_ID` es obligatorio (autor del post en GHL); ya viene puesto en `.env.example`
y `render.yaml`.

> Nota: en Render el disco es efímero, así que las ediciones del perfil/referencias
> persisten hasta el próximo redeploy. Para persistencia total, mover `data/` a una base
> de datos (v2).

## Notas

- **Lovart**: usamos su cliente oficial tal cual (no reimplementamos su firma).
  Si Lovart pide confirmación por costo alto, `generate` devuelve
  `warning: "pending_confirmation"` y puedes confirmar con `/api/lovart/confirm`.
- **GHL create draft**: el cuerpo (`summary`, `media`, `status:"draft"`) sigue la
  API pública del Social Planner. Conviene verificar los `accountIds` reales con
  `/api/ghl/accounts` antes de publicar.
- El flujo con **aprobación manual** vive en el frontend: generas un lote, marcas
  cuáles sí, y los aprobados se mandan a `/api/ghl/draft`.
