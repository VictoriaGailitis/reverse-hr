"""Credential-free, network-free PDF guest; per-request bounded child processes."""

import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from reverse_hr.contracts.resume_contracts import ExtractedPDF, PDFData
from reverse_hr.shared.decoder_isolation import require_isolation

LIMIT = 2 * 1024 * 1024


def child(operation, source, target, font, languages):
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
    from reverse_hr.services.candidate import resume_pdf

    resume_pdf.FONT = font
    resume_pdf.OCR_LANGUAGES = languages
    try:
        if sys.platform == "linux":
            from reverse_hr.services.candidate.resume_pdf_sandbox import restrict

            restrict(str(Path(source).parent))
        raw = Path(source).read_bytes()
        output = (
            resume_pdf.extract(raw).model_dump_json().encode()
            if operation == "extract"
            else resume_pdf.render(json.loads(raw))
        )
        Path(target).write_bytes(output)
    except Exception as exc:
        # Only a bounded error class leaves the guest; no parser diagnostics or source text.
        code = 75 if isinstance(exc, (RuntimeError, subprocess.SubprocessError, OSError)) else 65
        sys.exit(code)


def operation(kind, raw, font, languages):
    with tempfile.TemporaryDirectory(prefix="resume-") as directory:
        source, target = Path(directory) / "input", Path(directory) / "output"
        source.write_bytes(raw)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": directory,
        }
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "reverse_hr.services.candidate.resume_pdf_guest",
                    kind,
                    str(source),
                    str(target),
                    font,
                    languages,
                ],
                env=env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise HTTPException(503) from exc
        try:
            code = process.wait(timeout=35)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(503) from exc
        finally:
            # Kill the whole group, including any surviving OCR grandchildren.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        if code:
            raise HTTPException(422 if code == 65 else 503)
        if target.stat().st_size > LIMIT:
            raise HTTPException(422)
        return target.read_bytes()


def create_app(
    *, isolated=True, font="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", languages="eng+rus"
):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    slot = threading.BoundedSemaphore(1)

    def guard():
        if isolated:
            require_isolation()
        if not Path(font).is_file():
            raise HTTPException(503)

    @app.get("/ready")
    def ready():
        guard()
        if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
            raise HTTPException(503)
        available = (
            subprocess.run(
                ["tesseract", "--list-langs"], capture_output=True, timeout=3, check=True
            )
            .stdout.decode()
            .splitlines()
        )
        if not set(languages.split("+")) <= set(available):
            raise HTTPException(503)
        return {"ready": True}

    async def run(request, kind):
        guard()
        if not slot.acquire(blocking=False):
            raise HTTPException(503)
        try:
            raw = bytearray()
            async for part in request.stream():
                if len(raw) + len(part) > LIMIT:
                    raise HTTPException(413)
                raw.extend(part)
            if kind == "render":
                try:
                    PDFData.model_validate_json(raw)
                except ValueError as exc:
                    raise HTTPException(422) from exc
            result = await run_in_threadpool(operation, kind, bytes(raw), font, languages)
            if kind == "extract":
                return ExtractedPDF.model_validate_json(result)
            return Response(result, media_type="application/pdf")
        finally:
            slot.release()

    @app.post("/extract", response_model=ExtractedPDF)
    async def extract(request: Request):
        return await run(request, "extract")

    @app.post("/render")
    async def render(request: Request):
        return await run(request, "render")

    return app


if __name__ == "__main__":
    child(*sys.argv[1:])
