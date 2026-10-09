"""Private Unix socket only; Candidate never parses uploaded PDFs in-process."""

import http.client
import json
from pathlib import Path

from fastapi import HTTPException

from reverse_hr.media_decoder import UnixConnection
from reverse_hr.resume_contracts import ExtractedPDF, PDFData


class PDFGuest:
    def __init__(self, settings):
        self.path = settings.resume_pdf_socket

    def call(self, route, raw=None):
        if not self.path or not Path(self.path).is_absolute():
            raise HTTPException(503)
        connection = UnixConnection(self.path, 40)
        try:
            connection.request("GET" if raw is None else "POST", route, body=raw)
            response = connection.getresponse()
            body = response.read(2 * 1024 * 1024 + 1)
            if response.status == 422:
                raise HTTPException(422)
            if response.status != 200 or len(body) > 2 * 1024 * 1024:
                raise HTTPException(503)
            return body
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise HTTPException(503) from exc
        finally:
            connection.close()

    def ready(self):
        try:
            if json.loads(self.call("/ready")) != {"ready": True}:
                raise ValueError("Guest unavailable")
        except ValueError as exc:
            raise HTTPException(503) from exc

    def extract(self, raw):
        try:
            return ExtractedPDF.model_validate_json(self.call("/extract", raw))
        except ValueError as exc:
            raise HTTPException(503) from exc

    def render(self, data):
        raw = self.call("/render", PDFData.model_validate(data).model_dump_json().encode())
        if not raw.startswith(b"%PDF-"):
            raise HTTPException(503)
        return raw
