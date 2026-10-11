import base64
import json
from datetime import UTC, datetime


def canonical(model):
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def fresh(value, *, now=None):
    now = now or datetime.now(UTC)
    return value.tzinfo is not None and abs((now - value).total_seconds()) <= 30


def sign(signatures, context, model):
    return base64.b64encode(signatures.private.sign(context + canonical(model))).decode()


def verify(signatures, producer, signature, context, model):
    signatures.public[producer].verify(
        base64.b64decode(signature, validate=True), context + canonical(model)
    )
