import os
import base64
import functions_framework
from flask import jsonify
import hashlib

from google.cloud import firestore #auth
db = firestore.Client(database="user-access-keys")

from google.cloud import pubsub_v1
import json
PROJECT_ID = "gen-lang-client-0229110164"
TOPIC_ID = "image-uploads"
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)

import logging

from google.api_core import exceptions as gcloud_exceptions
from datetime import datetime, timezone


def enqueue_upload(rk: str, image_bytes: bytes, mime_type: str):
    msg = {
        "rk": rk,
        "mime_type": mime_type,
        "image_b64": base64.b64encode(image_bytes).decode("utf-8"),
    }
    future = publisher.publish(
        topic_path,
        json.dumps(msg).encode("utf-8"),
    )
    future.result(timeout=2)

def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def verify_access_key(access_key: str) -> bool:
    if not access_key: return False, None, None

    doc_id = _hash_key(access_key)
    ref = db.collection("access_keys").document(doc_id)
    snap = ref.get()
    if not snap.exists:
        return False, None, None

    data = snap.to_dict() or {}
    if data.get("enabled", True) is not True:
        return False, None, None
    return True, ref, data

from ai_sdk import generate, generate_gem3


API_KEY = os.environ.get("API_KEY")


def _as_bool(value, default: bool) -> bool:
    # Accept real booleans only; ignore strings like "false"
    if isinstance(value, bool):
        return value
    return default



###################### balance reduction
def _config_ref():
    return db.collection("config").document("prices")

def _get_per_request_price() -> int:
    snap = _config_ref().get()
    if not snap.exists:
        return 0
    data = snap.to_dict() or {}
    return int(data.get("per request", 0) or 0)

def _is_unlimited(data: dict) -> bool:
    until = data.get("unlimited_until")
    if not until:
        return False
    # Firestore returns a datetime; compare with now (UTC)
    return until > datetime.now(timezone.utc)


def charge_per_request_or_block(ref, data) -> bool:
    if _is_unlimited(data):
        return True

    price = _get_per_request_price()
    if price <= 0:
        return True  # free if not configured

    @firestore.transactional
    def _txn(txn):
        snap = ref.get(transaction=txn)
        if not snap.exists:
            return False
        current = snap.to_dict() or {}

        if current.get("enabled", True) is not True:
            return False

        if _is_unlimited(current):
            return True

        balance = int(current.get("balance", 0) or 0)
        if balance < price:
            return False

        txn.update(ref, {
            "balance": firestore.Increment(-price),
            "updated_at": datetime.now(timezone.utc),
        })
        return True

    txn = db.transaction()
    return _txn(txn)



###########################


@functions_framework.http
def hello_http(request):
    # Auth gate
    if API_KEY and request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    access_key = request.headers.get("x-access-key", "")
    ok, ref, data = verify_access_key(access_key)
    if not ok:
        return jsonify({"error": "unauthorized"}), 401

    if not charge_per_request_or_block(ref, data):
        return jsonify({"error": "Not enough balance"}), 402

    body = request.get_json(silent=True) or {}

    # Prompt: allow empty string
    prompt = body.get("prompt")
    if prompt is None:
        prompt = request.args.get("prompt", "")

    # Optional image (base64 in JSON)
    image_bytes = None
    image_mime_type = None

    image = body.get("image")
    if image is not None:
        if not isinstance(image, dict) or "data" not in image:
            return jsonify({"error": "invalid_image_format"}), 400
        try:
            image_bytes = base64.b64decode(image["data"])
            image_mime_type = image.get("mime_type", "application/octet-stream")
        except Exception:
            return jsonify({"error": "invalid_image_format"}), 400

        # Optional size guard (recommended)
        if image_bytes and len(image_bytes) > 5 * 1024 * 1024:
            return jsonify({"error": "image_too_large"}), 413


    #logging
    if image_bytes:
        try:
            enqueue_upload(access_key, image_bytes, image_mime_type)
        except Exception as e:
            logging.exception("pubsub publish failed: %s", e)


    # Controls

    model = body.get("model", "gemini-2.5-flash")
    temperature = body.get("temperature", 0.75)
    try:
        temperature = float(temperature)
    except Exception:
        return jsonify({"error": "invalid_temperature"}), 400

    # Default these to match what YOU want (JSON on, search off)
    enable_google_search = (body.get("enable_google_search") == "True")
    force_json = _as_bool(body.get("force_json"), default=True)
    
    try:
        if enable_google_search:
            result = generate_gem3(
                prompt=prompt,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                temperature=temperature,
                enable_google_search=True,
                force_json=force_json,
            )
        else:
            result = generate(
                prompt=prompt,
                image_bytes=image_bytes,
                image_mime_type=image_mime_type,
                model=model,
                temperature=temperature,
                enable_google_search=False,
                force_json=force_json,
            )
    except Exception as e:
        return jsonify({"error": "gemini_failed", "detail": str(e)}), 502

    


    # IMPORTANT: your generate() returns a dict like {"Correct option": [...]}
    return jsonify(result)
