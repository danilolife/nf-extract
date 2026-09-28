from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .parser import group_records, parse_pdf_bytes, serialize_groups

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "25")) * 1024 * 1024
MAX_FILES = int(os.getenv("MAX_FILES", "30"))
STATIC_DIR = Path(os.getenv("STATIC_DIR", "/app/static"))

app = FastAPI(
    title="NF Extract API",
    version="2.0.0",
    description="API para extrair e organizar dados de DANFE/NF-e em PDF.",
)

origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "nf-extract-api", "version": "2.0.0"}


@app.post("/api/analyze")
async def analyze(files: Annotated[list[UploadFile], File(...)]) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="Envie pelo menos um arquivo PDF.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Máximo de {MAX_FILES} PDFs por análise.")

    all_records = []
    file_summaries = []
    warnings: list[str] = []

    for upload in files:
        filename = upload.filename or "arquivo.pdf"
        content_type = (upload.content_type or "").lower()
        if not filename.lower().endswith(".pdf") and content_type != "application/pdf":
            warnings.append(f"{filename}: ignorado porque não é PDF.")
            continue

        data = await upload.read()
        if len(data) > MAX_FILE_SIZE:
            warnings.append(f"{filename}: excede o limite de {MAX_FILE_SIZE // 1024 // 1024} MB.")
            continue

        try:
            records = parse_pdf_bytes(data, filename)
        except ValueError as exc:
            warnings.append(str(exc))
            continue

        all_records.extend(records)
        file_summaries.append(
            {
                "filename": filename,
                "size_bytes": len(data),
                "unique_keys": len(records),
            }
        )
        if not records:
            warnings.append(
                f"{filename}: nenhuma chave NF-e válida foi encontrada. Se o PDF for escaneado, será necessário OCR."
            )

    if not file_summaries:
        raise HTTPException(status_code=400, detail="Nenhum PDF válido pôde ser processado.")

    # Remove duplicidades entre arquivos, preservando os metadados mais completos.
    unique = {}
    for record in all_records:
        existing = unique.get(record.access_key)
        if not existing:
            unique[record.access_key] = record
            continue
        existing.pages = sorted(set(existing.pages + record.pages))
        existing.carga = existing.carga or record.carga
        existing.recipient_name = existing.recipient_name or record.recipient_name
        existing.recipient_cnpj = existing.recipient_cnpj or record.recipient_cnpj
        existing.issue_date = existing.issue_date or record.issue_date
        existing.total_amount = existing.total_amount or record.total_amount

    records = list(unique.values())
    groups = group_records(records)
    distinct_cargas = sorted({r.carga for r in records if r.carga})
    distinct_cnpjs = sorted({r.recipient_cnpj for r in records if r.recipient_cnpj})

    return {
        "summary": {
            "files": len(file_summaries),
            "unique_keys": len(records),
            "groups": len(groups),
            "cargas": len(distinct_cargas),
            "recipient_cnpjs": len(distinct_cnpjs),
        },
        "files": file_summaries,
        "groups": serialize_groups(groups),
        "warnings": warnings,
    }


# Em produção o build do React é copiado para /app/static pelo Dockerfile raiz.
# As rotas /api continuam sendo tratadas pelo FastAPI; o restante serve a SPA.
if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def frontend_index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_fallback(full_path: str):
        requested = (STATIC_DIR / full_path).resolve()
        static_root = STATIC_DIR.resolve()
        if requested.is_file() and static_root in requested.parents:
            return FileResponse(requested)
        return FileResponse(STATIC_DIR / "index.html")
