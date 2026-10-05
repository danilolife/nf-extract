from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .parser import (
    aggregate_volume_total,
    group_records,
    is_image_filename,
    parse_image_bytes,
    parse_pdf_bytes,
    serialize_groups,
)
from .recipients import serialize_recipient_profiles
from .suppliers import serialize_supplier_profiles

MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "25")) * 1024 * 1024
MAX_FILES = int(os.getenv("MAX_FILES", "30"))
STATIC_DIR = Path(os.getenv("STATIC_DIR", "/app/static"))
IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

app = FastAPI(
    title="NF Extract API",
    version="3.0.0",
    description="API para extrair e organizar dados de DANFE/NF-e em PDF e fotos/imagens.",
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
    return {"status": "ok", "service": "nf-extract-api", "version": "3.0.0"}


@app.get("/api/suppliers")
def suppliers() -> dict:
    profiles = serialize_supplier_profiles()
    return {"count": len(profiles), "suppliers": profiles}




@app.get("/api/recipients")
def recipients() -> dict:
    profiles = serialize_recipient_profiles()
    return {"count": len(profiles), "recipients": profiles}

@app.post("/api/analyze")
async def analyze(files: Annotated[list[UploadFile], File(...)]) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="Envie pelo menos um PDF ou imagem.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Máximo de {MAX_FILES} arquivos por análise.")

    all_records = []
    file_summaries = []
    warnings: list[str] = []

    for upload in files:
        filename = upload.filename or "arquivo"
        lower_name = filename.lower()
        content_type = (upload.content_type or "").lower()
        is_pdf = lower_name.endswith(".pdf") or content_type == "application/pdf"
        is_image = is_image_filename(lower_name) or content_type in IMAGE_MIME_TYPES

        if not (is_pdf or is_image):
            warnings.append(f"{filename}: ignorado porque não é PDF nem imagem suportada.")
            continue

        data = await upload.read()
        if len(data) > MAX_FILE_SIZE:
            warnings.append(f"{filename}: excede o limite de {MAX_FILE_SIZE // 1024 // 1024} MB.")
            continue

        try:
            records = parse_pdf_bytes(data, filename) if is_pdf else parse_image_bytes(data, filename)
        except ValueError as exc:
            warnings.append(str(exc))
            continue

        all_records.extend(records)
        file_summaries.append(
            {
                "filename": filename,
                "size_bytes": len(data),
                "unique_keys": len(records),
                "kind": "pdf" if is_pdf else "imagem",
                "ocr_used": any(record.extraction_method == "ocr" for record in records),
                "volume_records": sum(1 for record in records if record.volume_count is not None),
                "total_volumes": aggregate_volume_total(records),
            }
        )
        if not records:
            warnings.append(
                f"{filename}: nenhuma chave NF-e válida foi encontrada. Verifique se a imagem está legível ou se o documento contém a DANFE completa."
            )

    if not file_summaries:
        raise HTTPException(status_code=400, detail="Nenhum arquivo válido pôde ser processado.")

    # Remove duplicidades entre arquivos sem misturar metadados conflitantes.
    # A mesma chave jamais pode trocar de destinatário silenciosamente.
    unique = {}
    conflicts: list[str] = []
    recipient_conflicted_keys: set[str] = set()
    carga_conflicted_keys: set[str] = set()
    for record in all_records:
        existing = unique.get(record.access_key)
        if not existing:
            unique[record.access_key] = record
            continue

        existing.pages = sorted(set(existing.pages + record.pages))

        recipient_conflict = (
            existing.recipient_cnpj
            and record.recipient_cnpj
            and existing.recipient_cnpj != record.recipient_cnpj
        )
        carga_conflict = existing.carga and record.carga and existing.carga != record.carga

        if recipient_conflict:
            recipient_conflicted_keys.add(record.access_key)
            conflicts.append(
                f"Conflito na chave {record.access_key}: CNPJ destinatário divergente "
                f"({existing.recipient_cnpj} x {record.recipient_cnpj}). O CNPJ foi ocultado para revisão."
            )
            existing.recipient_name = None
            existing.recipient_cnpj = None
            existing.recipient_cnpj_valid = False
            existing.binding_verified = False
        elif record.access_key not in recipient_conflicted_keys and not existing.recipient_cnpj and record.recipient_cnpj:
            existing.recipient_name = record.recipient_name
            existing.recipient_cnpj = record.recipient_cnpj
            existing.recipient_cnpj_valid = record.recipient_cnpj_valid

        if carga_conflict:
            carga_conflicted_keys.add(record.access_key)
            conflicts.append(
                f"Conflito na chave {record.access_key}: cargas divergentes "
                f"({existing.carga} x {record.carga}). A carga foi ocultada para revisão."
            )
            existing.carga = None
            existing.binding_verified = False
        elif record.access_key not in carga_conflicted_keys and not existing.carga and record.carga:
            existing.carga = record.carga

        existing.issuer_name = existing.issuer_name or record.issuer_name
        existing.issuer_cnpj = existing.issuer_cnpj or record.issuer_cnpj
        existing.supplier_profile_id = existing.supplier_profile_id or record.supplier_profile_id
        existing.supplier_recognized = existing.supplier_recognized or record.supplier_recognized
        existing.issue_date = existing.issue_date or record.issue_date
        existing.total_amount = existing.total_amount or record.total_amount
        existing.volume_count = existing.volume_count or record.volume_count
        existing.volume_species = existing.volume_species or record.volume_species
        if record.access_key not in recipient_conflicted_keys:
            existing.recipient_cnpj_valid = existing.recipient_cnpj_valid or record.recipient_cnpj_valid
            existing.recipient_registered = existing.recipient_registered or record.recipient_registered
            existing.recipient_registry_name = existing.recipient_registry_name or record.recipient_registry_name
            if existing.recipient_name_matches_registry is None:
                existing.recipient_name_matches_registry = record.recipient_name_matches_registry
        if record.access_key in recipient_conflicted_keys or record.access_key in carga_conflicted_keys:
            existing.binding_verified = False
        else:
            existing.binding_verified = existing.binding_verified or record.binding_verified
            if existing.recipient_registered and existing.recipient_name_matches_registry is False:
                existing.binding_verified = False
        if existing.volume_mode == "per_invoice" and record.volume_mode != "per_invoice":
            existing.volume_mode = record.volume_mode
        if record.extraction_method == "ocr":
            existing.extraction_method = "ocr"
            existing.ocr_rotation = record.ocr_rotation or existing.ocr_rotation
        if record.source_kind == "imagem":
            existing.source_kind = "imagem"

    warnings.extend(conflicts)
    records = list(unique.values())
    groups = group_records(records)
    distinct_cargas = sorted({r.carga for r in records if r.carga})
    distinct_cnpjs = sorted({r.recipient_cnpj for r in records if r.recipient_cnpj})
    distinct_issuers = sorted({r.issuer_cnpj for r in records if r.issuer_cnpj})
    ocr_records = sum(1 for r in records if r.extraction_method == "ocr")
    image_records = sum(1 for r in records if r.source_kind == "imagem")
    recognized_supplier_records = sum(1 for r in records if r.supplier_recognized)
    unknown_supplier_records = sum(1 for r in records if not r.supplier_recognized)
    volume_records = sum(1 for r in records if r.volume_count is not None)
    total_volumes = aggregate_volume_total(records)
    verified_bindings = sum(1 for r in records if r.binding_verified)
    review_bindings = len(records) - verified_bindings
    registered_recipient_records = sum(1 for r in records if r.recipient_registered)
    recipient_registry_mismatches = sum(
        1 for r in records if r.recipient_registered and r.recipient_name_matches_registry is False
    )
    for record in records:
        if record.recipient_registered and record.recipient_name_matches_registry is False:
            warnings.append(
                f"NF {record.nf_number}: o CNPJ {record.recipient_cnpj} está cadastrado como "
                f"{record.recipient_registry_name}, mas o nome lido foi {record.recipient_name or 'não identificado'}. Revisar vínculo."
            )

    return {
        "summary": {
            "files": len(file_summaries),
            "unique_keys": len(records),
            "groups": len(groups),
            "cargas": len(distinct_cargas),
            "recipient_cnpjs": len(distinct_cnpjs),
            "issuers": len(distinct_issuers),
            "ocr_records": ocr_records,
            "image_records": image_records,
            "recognized_supplier_records": recognized_supplier_records,
            "unknown_supplier_records": unknown_supplier_records,
            "volume_records": volume_records,
            "missing_volume_records": len(records) - volume_records,
            "total_volumes": total_volumes,
            "verified_bindings": verified_bindings,
            "review_bindings": review_bindings,
            "integrity_conflicts": len(conflicts),
            "registered_recipient_records": registered_recipient_records,
            "recipient_registry_mismatches": recipient_registry_mismatches,
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
