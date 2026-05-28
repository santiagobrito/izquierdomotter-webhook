"""
Webhook receptor de Elementor Pro Forms → uploader de conversiones a Google Ads.

Flujo:
  Form Elementor → POST /webhook/elementor → Google Ads ClickConversionUpload
                                          + Enhanced Conversions for Leads (email/phone hashed)

Conversion action de destino: (web) generate_lead — id 6603919625
Cuenta Ads: 7379203565 (Izquierdo Motter, bajo MCC 3295205058)
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from google.ads.googleads.client import GoogleAdsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("webhook")

CUSTOMER_ID = "7379203565"
CONVERSION_ACTION_ID = "6603919625"
SHARED_SECRET = os.environ["WEBHOOK_SECRET"]
DEFAULT_CONVERSION_VALUE = float(os.environ.get("CONVERSION_VALUE", "1.0"))
DEFAULT_CURRENCY = os.environ.get("CONVERSION_CURRENCY", "EUR")

app = FastAPI(title="IM webhook")

_ads_client: GoogleAdsClient | None = None


def get_ads_client() -> GoogleAdsClient:
    global _ads_client
    if _ads_client is None:
        config = {
            "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
            "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
            "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
            "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
            "use_proto_plus": True,
        }
        _ads_client = GoogleAdsClient.load_from_dict(config)
    return _ads_client


def sha256_norm(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 9 and not digits.startswith("34"):
        digits = "34" + digits
    return "+" + digits


def pick_field(fields: dict, *names) -> str:
    """Busca un valor entre varios nombres posibles (case-insensitive, ignora espacios)."""
    lower_map = {k.lower().strip(): v for k, v in fields.items() if isinstance(v, (str, int, float))}
    for name in names:
        v = lower_map.get(name.lower().strip())
        if v:
            return str(v).strip()
    return ""


def parse_elementor_payload(data: dict) -> dict:
    """
    Elementor Pro Webhook envía un POST application/x-www-form-urlencoded
    o JSON con estructura tipo:
        {
            "form": {"id": "abc", "name": "Form servicios 2026"},
            "fields": {"email": "x@y.com", "name": "Juan", ...}
        }
    También puede mandar los fields al top-level. Soportamos ambos.
    """
    fields = {}
    if isinstance(data.get("fields"), dict):
        fields = data["fields"]
    if isinstance(data.get("form_fields"), dict):
        fields = {**fields, **data["form_fields"]}
    # Top-level fallback
    for k, v in data.items():
        if k in ("form", "fields", "form_fields", "meta"):
            continue
        if isinstance(v, (str, int, float)):
            fields.setdefault(k, v)
    return fields


@app.get("/")
async def health():
    return {"status": "ok", "service": "im-webhook"}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/webhook/elementor")
async def webhook_elementor(
    request: Request,
    secret: str | None = None,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
):
    # Auth: aceptamos secret por query string (Elementor Webhook no permite headers custom)
    # o por header X-Webhook-Secret (curl/testing).
    provided = secret or x_webhook_secret
    if provided != SHARED_SECRET:
        log.warning("Forbidden: bad or missing secret")
        raise HTTPException(status_code=403, detail="Forbidden")

    # Parse body (Elementor puede enviar JSON o form-encoded)
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            raw = await request.json()
        else:
            form = await request.form()
            raw = {k: form.get(k) for k in form.keys()}
    except Exception as e:
        log.exception("Failed to parse body")
        raise HTTPException(status_code=400, detail=f"Bad body: {e}")

    fields = parse_elementor_payload(raw)
    log.info("Webhook received fields=%s", list(fields.keys()))

    gclid = pick_field(fields, "gclid")
    wbraid = pick_field(fields, "wbraid")
    gbraid = pick_field(fields, "gbraid")
    email = pick_field(fields, "email", "correo", "tu correo electrónico")
    phone = pick_field(fields, "phone", "telefono", "teléfono", "tel")
    name = pick_field(fields, "name", "nombre")

    has_click_id = bool(gclid or wbraid or gbraid)

    if not has_click_id:
        # ClickConversion requiere obligatoriamente uno de gclid/wbraid/gbraid.
        # Sin él no podemos atribuir → skip y registrar (no es error).
        log.info("Submit sin click_id (visita orgánica/directa) → skip")
        return JSONResponse(
            {"status": "skipped", "reason": "no gclid/wbraid/gbraid"},
            status_code=200,
        )

    try:
        client = get_ads_client()

        click_conversion = client.get_type("ClickConversion")
        click_conversion.conversion_action = client.get_service(
            "ConversionActionService"
        ).conversion_action_path(CUSTOMER_ID, CONVERSION_ACTION_ID)

        if gclid:
            click_conversion.gclid = gclid
        elif wbraid:
            click_conversion.wbraid = wbraid
        elif gbraid:
            click_conversion.gbraid = gbraid

        click_conversion.conversion_date_time = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S+00:00"
        )
        click_conversion.conversion_value = DEFAULT_CONVERSION_VALUE
        click_conversion.currency_code = DEFAULT_CURRENCY

        # Enhanced Conversions for Leads — datos hasheados SHA-256
        if email:
            ui = client.get_type("UserIdentifier")
            ui.hashed_email = sha256_norm(email)
            click_conversion.user_identifiers.append(ui)
        if phone:
            normalized = normalize_phone(phone)
            if normalized:
                ui = client.get_type("UserIdentifier")
                ui.hashed_phone_number = sha256_norm(normalized)
                click_conversion.user_identifiers.append(ui)

        upload_service = client.get_service("ConversionUploadService")
        response = upload_service.upload_click_conversions(
            customer_id=CUSTOMER_ID,
            conversions=[click_conversion],
            partial_failure=True,
        )
    except Exception as e:
        # No devolvemos 5xx para que Elementor no reintente.
        # Devolvemos 200 con detalle del error para diagnóstico.
        log.exception("Upload pipeline failed")
        return JSONResponse(
            {"status": "error", "error": f"{type(e).__name__}: {str(e)[:500]}"},
            status_code=200,
        )

    # Partial failure check
    if response.partial_failure_error and response.partial_failure_error.message:
        log.error("Partial failure: %s", response.partial_failure_error.message)
        return JSONResponse(
            {
                "status": "partial_failure",
                "error": response.partial_failure_error.message,
            },
            status_code=200,
        )

    result_summary = {
        "status": "ok",
        "uploaded": len(response.results),
        "gclid": bool(gclid),
        "wbraid": bool(wbraid),
        "gbraid": bool(gbraid),
        "enhanced_email": bool(email),
        "enhanced_phone": bool(phone),
        "conversion_action": CONVERSION_ACTION_ID,
    }
    log.info("Upload OK: %s", json.dumps(result_summary))
    return result_summary
