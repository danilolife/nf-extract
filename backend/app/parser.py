from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Iterable

import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .suppliers import (
    extract_supplier_carga,
    get_supplier_profile,
    supplier_display_name,
    supplier_uses_carga as profile_uses_carga,
)

CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
CARGA_RE = re.compile(r"\b(?:NRO\s*)?CARGA\s*:?['\s-]*(\d{4,})\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
MONEY_RE = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
COMPANY_HINT_RE = re.compile(
    r"\b(?:LTDA|S/?A|S\.A\.|ME|EIRELI|COMERCIO|COMÉRCIO|SUPERMERCADO|"
    r"DISTRIBUIDORA|ATACADISTA|ATACAREJO|LOGISTICA|LOGÍSTICA)\b",
    re.IGNORECASE,
)

# Regras de fornecedor agora ficam centralizadas em suppliers.json.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass
class InvoiceRecord:
    access_key: str
    nf_number: str
    series: str
    model: str
    valid_key: bool
    carga: str | None = None
    recipient_name: str | None = None
    recipient_cnpj: str | None = None
    issuer_name: str | None = None
    issuer_cnpj: str | None = None
    supplier_profile_id: str | None = None
    supplier_recognized: bool = False
    issue_date: str | None = None
    total_amount: str | None = None
    pages: list[int] = field(default_factory=list)
    source_file: str | None = None
    source_kind: str = "pdf"
    extraction_method: str = "texto"
    ocr_rotation: int = 0


@dataclass
class GroupResult:
    carga: str | None
    recipient_cnpj: str
    recipient_name: str
    issuer_name: str
    issuer_cnpj: str
    invoices: list[InvoiceRecord]

    @property
    def key_count(self) -> int:
        return len(self.invoices)

    @property
    def group_type(self) -> str:
        return "carga" if self.carga else "destinatario"


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_text(value: str | None) -> str:
    raw = (value or "").upper()
    return "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")


def format_cnpj(value: str | None) -> str | None:
    digits = digits_only(value)
    if len(digits) != 14:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def issuer_cnpj_from_key(key: str) -> str | None:
    key = digits_only(key)
    if len(key) != 44:
        return None
    return format_cnpj(key[6:20])


def expected_nfe_dv(body43: str) -> int:
    body43 = digits_only(body43)
    if len(body43) != 43:
        return -1
    weight = 2
    total = 0
    for digit in reversed(body43):
        total += int(digit) * weight
        weight += 1
        if weight > 9:
            weight = 2
    remainder = total % 11
    dv = 11 - remainder
    return 0 if dv in (10, 11) else dv


def structurally_plausible_key(key: str) -> bool:
    key = digits_only(key)
    if len(key) != 44 or key[20:22] not in {"55", "65"}:
        return False
    if key[:2] not in {"11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26", "27", "28", "29", "31", "32", "33", "35", "41", "42", "43", "50", "51", "52", "53"}:
        return False
    month = int(key[4:6])
    return 1 <= month <= 12 and int(key[25:34]) > 0


def validate_nfe_key(key: str) -> bool:
    """Validate a 44-digit NF-e/NFC-e access key using the modulo-11 DV."""
    key = digits_only(key)
    if not structurally_plausible_key(key):
        return False
    return expected_nfe_dv(key[:43]) == int(key[43])


def repair_ocr_dv(key: str) -> str | None:
    """Repair only the final DV when OCR read the first 43 digits plausibly."""
    key = digits_only(key)
    if not structurally_plausible_key(key):
        return None
    repaired = f"{key[:43]}{expected_nfe_dv(key[:43])}"
    return repaired if validate_nfe_key(repaired) else None


def extract_access_keys(text: str) -> list[str]:
    """Extract NF-e access keys robustly across supplier layouts and OCR.

    The Farpani layout, for example, places issuer CNPJ values immediately before
    the access key. A naive 44-digit whitespace regex can begin inside that CNPJ.
    We therefore try line-level candidates and token windows first, validating
    every candidate with the NF-e check digit.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add_candidate(raw: str) -> None:
        key = digits_only(raw)
        if len(key) != 44:
            return
        candidate = key if validate_nfe_key(key) else repair_ocr_dv(key)
        if candidate and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)

    def scan_segment(segment: str) -> None:
        # 1) Exact line candidates are the strongest signal for text PDFs.
        for line in segment.splitlines():
            line_digits = digits_only(line)
            if 43 <= len(line_digits) <= 45:
                if len(line_digits) == 44:
                    add_candidate(line_digits)

        # 2) DANFE keys are commonly printed in eleven groups of four digits.
        for match in re.finditer(r"(?<!\d)(?:\d{4}[ \t\r\n]+){10}\d{4}(?!\d)", segment):
            add_candidate(match.group(0))

        # 3) OCR may split groups irregularly. Slide over numeric tokens and test
        # concatenations that total exactly 44 digits.
        tokens = re.findall(r"\d+", segment)
        for i in range(len(tokens)):
            combined = ""
            for j in range(i, min(i + 16, len(tokens))):
                combined += tokens[j]
                if len(combined) == 44:
                    add_candidate(combined)
                    break
                if len(combined) > 44:
                    break

        # 4) Last fallback for OCR that preserves only whitespace between digits.
        for raw in re.findall(r"(?<!\d)(?:\d[\s\r\n]*){44}(?!\d)", segment):
            add_candidate(raw)

    # Prefer the section immediately after a key label.
    for match in re.finditer(r"CHAVE\s+DE\s+ACESSO(?:\s+DA\s+NF-?E)?", text, flags=re.IGNORECASE):
        scan_segment(text[match.end() : match.end() + 420])

    if not found:
        scan_segment(text)

    return found


def _clean_company_name(value: str) -> str:
    name = re.sub(r"\s+", " ", value).strip(" -\t,;:")
    # Common customer/internal code suffix in DANFE, e.g. "REDE BOM ... LTDA - 28781".
    name = re.sub(r"\s*[-–]\s*\d{2,}\s*$", "", name).strip()
    return name


def _looks_like_company_name(value: str) -> bool:
    candidate = _clean_company_name(value)
    if len(candidate) < 4 or len(candidate) > 120:
        return False
    if CNPJ_RE.search(candidate) or DATE_RE.fullmatch(candidate):
        return False
    if re.fullmatch(r"[\d\s./:()\-]+", candidate):
        return False
    return bool(COMPANY_HINT_RE.search(candidate))


def extract_issuer_name(text: str, issuer_cnpj: str | None) -> str | None:
    """Best-effort issuer/company name for the current DANFE page."""
    issuer_digits = digits_only(issuer_cnpj)
    profile = get_supplier_profile(issuer_cnpj=issuer_cnpj)
    if profile:
        return profile.display_name

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # The receipt stub is very reliable across the suppliers seen so far.
    for line in lines:
        match = re.search(
            r"RECEB(?:I\(EMOS\)|EMOS)\s+DE\s+(.+?)(?:,\s*A\(S\)|\s+\d{2}/\d{2}/\d{4}|$)",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            name = _clean_company_name(match.group(1))
            if name:
                return name

    # Otherwise, locate the issuer CNPJ (derived from the access key) and use the
    # nearest company-like line before it.
    if issuer_digits:
        for index, line in enumerate(lines):
            if digits_only(line) != issuer_digits and issuer_cnpj not in line:
                continue
            for previous in reversed(lines[max(0, index - 30) : index]):
                if _looks_like_company_name(previous):
                    return _clean_company_name(previous)

    # Known textual patterns as final fallback.
    for line in lines:
        normalized = normalize_text(line)
        if "NORDIL" in normalized or "MULTIGIRO" in normalized or "GIRO RAPIDO" in normalized or "FARPANI" in normalized:
            if _looks_like_company_name(line):
                return _clean_company_name(line)
    return None


def supplier_uses_carga(issuer_name: str | None, issuer_cnpj: str | None) -> bool:
    return profile_uses_carga(issuer_cnpj=issuer_cnpj, issuer_name=issuer_name)


def _recipient_section_start(text: str) -> int:
    normalized = normalize_text(text)
    match = re.search(r"DESTINATARIO\s*/?\s*REMETENTE", normalized, flags=re.IGNORECASE)
    return match.start() if match else -1


def extract_recipient(text: str, issuer_cnpj: str | None = None) -> tuple[str | None, str | None]:
    """Return (recipient_name, recipient_cnpj) from the destinatário section.

    Some DANFE generators (e.g. Multigiro/G.R) output all field labels first and
    the values much later in the text stream. The issuer CNPJ can also appear
    inside that textual window before the recipient CNPJ. We therefore ignore
    the issuer CNPJ (known from the access key) and select the next company CNPJ.
    """
    start = _recipient_section_start(text)
    if start == -1:
        return None, None

    # A wider segment is necessary for generators that output the entire form
    # labels before actual values.
    segment = text[start : start + 3600]
    issuer_digits = digits_only(issuer_cnpj)

    chosen: re.Match[str] | None = None
    for match in CNPJ_RE.finditer(segment):
        if issuer_digits and digits_only(match.group(0)) == issuer_digits:
            continue
        chosen = match
        break

    if not chosen:
        return None, None

    recipient_cnpj = chosen.group(0)
    before = segment[: chosen.start()]
    lines = [line.strip() for line in before.splitlines() if line.strip()]

    # First try a company name on the same line as the CNPJ.
    raw_lines = before.splitlines()
    same_line = raw_lines[-1].strip() if raw_lines else ""
    if _looks_like_company_name(same_line):
        return _clean_company_name(same_line), recipient_cnpj

    # Choose the nearest company-like line before the recipient CNPJ. This works
    # for both Nordil (name/CNPJ together) and Multigiro (name several lines above).
    current_issuer_name = extract_issuer_name(text, issuer_cnpj)
    for line in reversed(lines):
        if _looks_like_company_name(line):
            candidate = _clean_company_name(line)
            # Don't accidentally return the issuer line.
            if normalize_text(candidate) == normalize_text(current_issuer_name):
                continue
            return candidate, recipient_cnpj

    return None, recipient_cnpj


def extract_issue_date(text: str, recipient_cnpj: str | None) -> str | None:
    start = _recipient_section_start(text)
    if start != -1:
        segment = text[start : start + 3600]
        # Prefer a date immediately after the recipient block when present.
        if recipient_cnpj:
            cnpj_pos = segment.find(recipient_cnpj)
            if cnpj_pos != -1:
                after = segment[cnpj_pos : cnpj_pos + 700]
                dates = DATE_RE.findall(after)
                # First date after recipient CNPJ is often due date on some layouts;
                # use dates before the CNPJ first when available.
                before_dates = DATE_RE.findall(segment[:cnpj_pos])
                if before_dates:
                    return before_dates[-2] if len(before_dates) >= 2 else before_dates[-1]
                if dates:
                    return dates[0]
        dates = DATE_RE.findall(segment)
        if dates:
            return dates[0]
    dates = DATE_RE.findall(text)
    return dates[0] if dates else None


def extract_total_amount(text: str) -> str | None:
    # Strong Multigiro/G.R signal.
    match = re.search(
        r"EMITIDA\s+EM\s+\d{2}/\d{2}/\d{4}\s+NO\s+VALOR\s+TOTAL\s+DE\s+(\d{1,3}(?:\.\d{3})*,\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1)

    # Strong Nordil signal in the receipt stub. This must not be applied to
    # every supplier: Farpani, for example, prints "Valor N.F.: R$ 0,00" in
    # the receipt while the actual invoice total appears in the tax totals.
    issuer_name_hint = extract_issuer_name(text, None)
    if supplier_uses_carga(issuer_name_hint, None):
        for receipt_pattern in (r"RECEBEMOS\s+DE", r"RECEBI\(EMOS\)\s+DE"):
            receipt = re.search(receipt_pattern, text, flags=re.IGNORECASE)
            if receipt:
                window = text[receipt.start() : receipt.start() + 420]
                values = MONEY_RE.findall(window)
                if values:
                    return values[0]

    # Generic fallback: look around the total section and choose the largest
    # monetary value found. Larger window supports label-first text extraction.
    marker = re.search(r"VALOR\s+TOTAL\s+DA\s+NOTA", text, flags=re.IGNORECASE)
    if marker:
        window = text[marker.end() : marker.end() + 3200]
        values = MONEY_RE.findall(window)
        if values:
            def money_number(value: str) -> float:
                return float(value.replace(".", "").replace(",", "."))

            return max(values, key=money_number)
    return None


def preprocess_image_for_ocr(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("L")
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.SHARPEN)
    image = ImageEnhance.Contrast(image).enhance(1.9)

    width, height = image.size
    max_side = max(width, height)
    min_side = min(width, height)

    # Keep phone photos sharp enough for OCR without sending 12–48 MP images
    # through Tesseract at full resolution on the server.
    if max_side > 3200:
        scale = 3200 / max_side
        image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    elif min_side < 1400:
        scale = min(3.0, 1400 / max(1, min_side))
        image = image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    return image


def _ocr_once(image: Image.Image, psm: int = 6) -> str:
    processed = preprocess_image_for_ocr(image)
    config = f"--oem 1 --psm {psm} -l por+eng"
    try:
        return pytesseract.image_to_string(processed, config=config) or ""
    except pytesseract.TesseractNotFoundError as exc:  # pragma: no cover
        raise ValueError(
            "OCR não está disponível no servidor. Instale o Tesseract ou use a imagem Docker atualizada."
        ) from exc
    except Exception:
        return ""


def _ocr_score(text: str) -> int:
    if not text.strip():
        return 0
    score = min(len(text), 5000) // 80
    upper = normalize_text(text)
    digit_count = len(re.findall(r"\d", text))
    score += min(digit_count // 8, 20)
    score += 50 * len(extract_access_keys(text))
    score += 8 * len(CNPJ_RE.findall(text))
    for marker in ("CHAVE", "ACESS", "DESTINATARIO", "REMETENTE", "DANFE", "NOTA FISCAL"):
        if marker in upper:
            score += 8
    return score


def ocr_image_best(image: Image.Image) -> tuple[str, int]:
    """OCR with automatic orientation fallback. Returns (text, clockwise rotation used)."""
    base = ImageOps.exif_transpose(image)
    attempts: list[tuple[int, str]] = []

    # Start with the original image. If a valid key is found, avoid extra OCR rotations.
    first = _ocr_once(base, psm=6)
    attempts.append((0, first))
    if extract_access_keys(first):
        sparse = _ocr_once(base, psm=11)
        return (f"{first}\n{sparse}".strip(), 0)

    # Photos commonly arrive sideways. Try quarter-turns before 180°.
    for angle in (90, 270, 180):
        rotated = base.rotate(-angle, expand=True)
        text = _ocr_once(rotated, psm=6)
        attempts.append((angle, text))
        if extract_access_keys(text):
            sparse = _ocr_once(rotated, psm=11)
            return (f"{text}\n{sparse}".strip(), angle)

    angle, best = max(attempts, key=lambda item: _ocr_score(item[1]))
    selected = base if angle == 0 else base.rotate(-angle, expand=True)
    sparse = _ocr_once(selected, psm=11)
    return (f"{best}\n{sparse}".strip(), angle)


def _page_text_from_pdf_page(page: fitz.Page) -> tuple[str, str, int]:
    text = page.get_text("text") or ""
    if extract_access_keys(text):
        return text, "texto", 0

    # Avoid expensive OCR on native-text pages such as boleto pages. OCR is
    # triggered for image-only/sparse pages or when a DANFE/key label exists but
    # native extraction failed to recover a valid key.
    normalized = normalize_text(text)
    should_ocr = len(text.strip()) < 220 or ("DANFE" in normalized and "CHAVE" in normalized)
    if not should_ocr:
        return text, "texto", 0

    # OCR fallback for scanned/image-based pages or poor native text extraction.
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image = Image.open(BytesIO(pix.tobytes("png")))
    ocr_text, rotation = ocr_image_best(image)
    if not text.strip():
        return ocr_text, "ocr", rotation
    if ocr_text:
        return f"{text}\n{ocr_text}", "ocr", rotation
    return text, "texto", 0


def _build_records_from_page_texts(
    page_texts: list[tuple[int, str, str, int]],
    filename: str,
    source_kind: str,
) -> list[InvoiceRecord]:
    records_by_key: dict[str, InvoiceRecord] = {}
    context_by_issuer: dict[str, dict[str, str | None]] = defaultdict(
        lambda: {"carga": None, "recipient_name": None, "recipient_cnpj": None, "issuer_name": None}
    )

    for page_number, text, extraction_method, ocr_rotation in page_texts:
        if not text.strip():
            continue

        keys = extract_access_keys(text)
        if not keys:
            continue

        for key in keys:
            issuer_cnpj = issuer_cnpj_from_key(key)
            issuer_id = digits_only(issuer_cnpj) or "unknown"
            context = context_by_issuer[issuer_id]

            issuer_name = extract_issuer_name(text, issuer_cnpj) or context["issuer_name"]
            issuer_name = supplier_display_name(issuer_cnpj, issuer_name)
            profile = get_supplier_profile(issuer_cnpj=issuer_cnpj, issuer_name=issuer_name)
            if issuer_name:
                context["issuer_name"] = issuer_name

            recipient_name, recipient_cnpj = extract_recipient(text, issuer_cnpj)
            if recipient_cnpj:
                context["recipient_cnpj"] = recipient_cnpj
                context["recipient_name"] = recipient_name or context["recipient_name"]
            else:
                recipient_cnpj = context["recipient_cnpj"]
                recipient_name = context["recipient_name"]

            carga: str | None = None
            if supplier_uses_carga(issuer_name, issuer_cnpj):
                carga = extract_supplier_carga(text, issuer_cnpj, issuer_name) or context["carga"]
                if carga:
                    context["carga"] = carga
            else:
                context["carga"] = None

            issue_date = extract_issue_date(text, recipient_cnpj)
            total_amount = extract_total_amount(text)
            nf_number = str(int(key[25:34]))
            series = str(int(key[22:25]))
            model = key[20:22]

            if key not in records_by_key:
                records_by_key[key] = InvoiceRecord(
                    access_key=key,
                    nf_number=nf_number,
                    series=series,
                    model=model,
                    valid_key=validate_nfe_key(key),
                    carga=carga,
                    recipient_name=recipient_name,
                    recipient_cnpj=recipient_cnpj,
                    issuer_name=issuer_name,
                    issuer_cnpj=issuer_cnpj,
                    supplier_profile_id=profile.id if profile else None,
                    supplier_recognized=bool(profile),
                    issue_date=issue_date,
                    total_amount=total_amount,
                    pages=[page_number],
                    source_file=filename,
                    source_kind=source_kind,
                    extraction_method=extraction_method,
                    ocr_rotation=ocr_rotation,
                )
            else:
                record = records_by_key[key]
                if page_number not in record.pages:
                    record.pages.append(page_number)
                record.carga = record.carga or carga
                record.recipient_name = record.recipient_name or recipient_name
                record.recipient_cnpj = record.recipient_cnpj or recipient_cnpj
                record.issuer_name = record.issuer_name or issuer_name
                record.issuer_cnpj = record.issuer_cnpj or issuer_cnpj
                record.supplier_profile_id = record.supplier_profile_id or (profile.id if profile else None)
                record.supplier_recognized = record.supplier_recognized or bool(profile)
                record.issue_date = record.issue_date or issue_date
                record.total_amount = record.total_amount or total_amount
                if extraction_method == "ocr":
                    record.extraction_method = "ocr"
                    record.ocr_rotation = ocr_rotation or record.ocr_rotation

    return list(records_by_key.values())


def parse_pdf_bytes(pdf_bytes: bytes, filename: str) -> list[InvoiceRecord]:
    try:
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Não foi possível abrir o PDF '{filename}': {exc}") from exc

    try:
        page_texts = []
        for page_index in range(doc.page_count):
            text, method, rotation = _page_text_from_pdf_page(doc.load_page(page_index))
            page_texts.append((page_index + 1, text, method, rotation))
    finally:
        doc.close()

    return _build_records_from_page_texts(page_texts, filename, source_kind="pdf")


def parse_image_bytes(image_bytes: bytes, filename: str) -> list[InvoiceRecord]:
    try:
        image = Image.open(BytesIO(image_bytes))
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Não foi possível abrir a imagem '{filename}': {exc}") from exc

    text, rotation = ocr_image_best(image)
    if not text.strip():
        return []
    return _build_records_from_page_texts([(1, text, "ocr", rotation)], filename, source_kind="imagem")


def is_image_filename(filename: str | None) -> bool:
    if not filename:
        return False
    name = filename.lower().strip()
    return any(name.endswith(ext) for ext in IMAGE_EXTENSIONS)


def group_records(records: Iterable[InvoiceRecord]) -> list[GroupResult]:
    # Carga groups remain separated by issuer + recipient. Non-carga suppliers are
    # grouped by issuer + recipient CNPJ so Multigiro/G.R never receive a fake load.
    buckets: dict[tuple[str, str, str, str, str], list[InvoiceRecord]] = defaultdict(list)
    for record in records:
        cnpj = record.recipient_cnpj or "CNPJ NÃO IDENTIFICADO"
        name = record.recipient_name or "DESTINATÁRIO NÃO IDENTIFICADO"
        issuer_name = record.issuer_name or "FORNECEDOR NÃO IDENTIFICADO"
        issuer_cnpj = record.issuer_cnpj or "CNPJ DO FORNECEDOR NÃO IDENTIFICADO"
        if record.carga:
            # For Nordil/Nordil Maré, carga + destinatário is the operational group.
            key = ("carga", record.carga, cnpj, issuer_cnpj, name)
        else:
            # For suppliers without operational carga, group only by recipient CNPJ.
            # The issuer remains available per invoice and as a frontend filter.
            key = ("destinatario", "", cnpj, "", name)
        buckets[key].append(record)

    groups: list[GroupResult] = []
    for (_group_type, carga, cnpj, _bucket_issuer_cnpj, name), invoices in buckets.items():
        invoices.sort(key=lambda x: (int(x.nf_number) if x.nf_number.isdigit() else 0, x.access_key))
        issuer_names = sorted({x.issuer_name for x in invoices if x.issuer_name})
        issuer_cnpjs = sorted({x.issuer_cnpj for x in invoices if x.issuer_cnpj})
        issuer_name = issuer_names[0] if len(issuer_names) == 1 else ("VÁRIOS FORNECEDORES" if issuer_names else "FORNECEDOR NÃO IDENTIFICADO")
        issuer_cnpj = issuer_cnpjs[0] if len(issuer_cnpjs) == 1 else ("VÁRIOS CNPJS" if issuer_cnpjs else "CNPJ DO FORNECEDOR NÃO IDENTIFICADO")
        groups.append(
            GroupResult(
                carga=carga or None,
                recipient_cnpj=cnpj,
                recipient_name=name,
                issuer_name=issuer_name,
                issuer_cnpj=issuer_cnpj,
                invoices=invoices,
            )
        )

    groups.sort(
        key=lambda g: (
            0 if g.carga else 1,
            g.carga or "",
            normalize_text(g.issuer_name),
            g.recipient_cnpj,
        )
    )
    return groups


def serialize_groups(groups: list[GroupResult]) -> list[dict]:
    payload: list[dict] = []
    for group in groups:
        payload.append(
            {
                "group_type": group.group_type,
                "carga": group.carga,
                "recipient_cnpj": group.recipient_cnpj,
                "recipient_name": group.recipient_name,
                "issuer_name": group.issuer_name,
                "issuer_cnpj": group.issuer_cnpj,
                "key_count": group.key_count,
                "invoices": [asdict(invoice) for invoice in group.invoices],
            }
        )
    return payload
