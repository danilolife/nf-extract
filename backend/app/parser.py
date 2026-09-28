from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Iterable

import fitz  # PyMuPDF

CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
CARGA_RE = re.compile(r"\b(?:NRO\s*)?CARGA\s*:?[\s-]*(\d{4,})\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
MONEY_RE = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
COMPANY_HINT_RE = re.compile(
    r"\b(?:LTDA|S/?A|S\.A\.|ME|EIRELI|COMERCIO|COMÉRCIO|SUPERMERCADO|"
    r"DISTRIBUIDORA|ATACADISTA|ATACAREJO|LOGISTICA|LOGÍSTICA)\b",
    re.IGNORECASE,
)

# Regra de negócio solicitada: carga operacional é usada apenas para DANFEs da
# Nordil (incluindo variações como Nordil Maré). Outros fornecedores podem
# imprimir "NroCarga" em observações/boletos, mas esse número não deve virar
# agrupamento de carga no sistema.
KNOWN_NORDIL_CNPJS = {"03775813000141"}
KNOWN_ISSUER_NAMES = {
    "03775813000141": "NORDIL-NORDESTE DISTRIBUICAO E LOGISTICA LTDA",
    "00728165000184": "MULTIGIRO DISTRIBUIDORA LTDA",
    "07973261000137": "G.R DISTRIBUIDORA LTDA",
}


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
    issue_date: str | None = None
    total_amount: str | None = None
    pages: list[int] = field(default_factory=list)
    source_file: str | None = None


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


def validate_nfe_key(key: str) -> bool:
    """Validate a 44-digit NF-e/NFC-e access key using the modulo-11 DV."""
    key = digits_only(key)
    if len(key) != 44:
        return False
    if key[20:22] not in {"55", "65"}:
        return False

    body = key[:43]
    expected = int(key[43])
    weight = 2
    total = 0
    for digit in reversed(body):
        total += int(digit) * weight
        weight += 1
        if weight > 9:
            weight = 2
    remainder = total % 11
    dv = 11 - remainder
    if dv in (10, 11):
        dv = 0
    return dv == expected


def extract_access_keys(text: str) -> list[str]:
    """Extract and validate NF-e access keys, tolerating spaces/newlines between digits."""
    found: list[str] = []
    seen: set[str] = set()

    # Strong signal: locate keys in the vicinity of the DANFE label.
    for match in re.finditer(r"CHAVE\s+DE\s+ACESSO", text, flags=re.IGNORECASE):
        window = text[match.end() : match.end() + 260]
        for raw in re.findall(r"(?:\d[\s\r\n]*){44}", window):
            key = digits_only(raw)
            if len(key) == 44 and validate_nfe_key(key) and key not in seen:
                seen.add(key)
                found.append(key)

    # Fallback: scan the full page, but only accept valid model + DV.
    if not found:
        for raw in re.findall(r"(?:\d[\s\r\n]*){44}", text):
            key = digits_only(raw)
            if len(key) == 44 and validate_nfe_key(key) and key not in seen:
                seen.add(key)
                found.append(key)

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
    if issuer_digits in KNOWN_ISSUER_NAMES:
        return KNOWN_ISSUER_NAMES[issuer_digits]

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
        if "NORDIL" in normalized or "MULTIGIRO" in normalized or "GIRO RAPIDO" in normalized:
            if _looks_like_company_name(line):
                return _clean_company_name(line)
    return None


def supplier_uses_carga(issuer_name: str | None, issuer_cnpj: str | None) -> bool:
    normalized = normalize_text(issuer_name)
    if "NORDIL" in normalized:
        return True
    return digits_only(issuer_cnpj) in KNOWN_NORDIL_CNPJS


def extract_recipient(text: str, issuer_cnpj: str | None = None) -> tuple[str | None, str | None]:
    """Return (recipient_name, recipient_cnpj) from the destinatário section.

    Some DANFE generators (e.g. Multigiro/G.R) output all field labels first and
    the values much later in the text stream. The issuer CNPJ can also appear
    inside that textual window before the recipient CNPJ. We therefore ignore
    the issuer CNPJ (known from the access key) and select the next company CNPJ.
    """
    upper = normalize_text(text)
    marker = "DESTINATARIO/REMETENTE"
    start = upper.find(marker)
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
    for line in reversed(lines):
        if _looks_like_company_name(line):
            candidate = _clean_company_name(line)
            # Don't accidentally return the issuer line.
            if normalize_text(candidate) == normalize_text(extract_issuer_name(text, issuer_cnpj)):
                continue
            return candidate, recipient_cnpj

    return None, recipient_cnpj


def extract_issue_date(text: str, recipient_cnpj: str | None) -> str | None:
    upper = normalize_text(text)
    start = upper.find("DESTINATARIO/REMETENTE")
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

    # Strong Nordil signal in the receipt stub.
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


def parse_pdf_bytes(pdf_bytes: bytes, filename: str) -> list[InvoiceRecord]:
    try:
        doc = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
    except Exception as exc:  # pragma: no cover - FastAPI converts this to user-facing error
        raise ValueError(f"Não foi possível abrir o PDF '{filename}': {exc}") from exc

    records_by_key: dict[str, InvoiceRecord] = {}
    # Continuation pages can omit metadata. Keep context per issuer so data does
    # not bleed from one supplier to another in unified PDFs.
    context_by_issuer: dict[str, dict[str, str | None]] = defaultdict(
        lambda: {"carga": None, "recipient_name": None, "recipient_cnpj": None, "issuer_name": None}
    )

    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            if not text.strip():
                continue

            keys = extract_access_keys(text)
            if not keys:
                # Boleto/blank continuation pages are intentionally ignored.
                continue

            # A DANFE page normally has one key; if there are more, metadata is
            # resolved per key below using the same page text.
            for key in keys:
                issuer_cnpj = issuer_cnpj_from_key(key)
                issuer_id = digits_only(issuer_cnpj) or "unknown"
                context = context_by_issuer[issuer_id]

                issuer_name = extract_issuer_name(text, issuer_cnpj) or context["issuer_name"]
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
                    carga_match = CARGA_RE.search(text)
                    carga = carga_match.group(1) if carga_match else context["carga"]
                    if carga:
                        context["carga"] = carga
                else:
                    # Explicitly discard Multigiro/G.R/other operational "NroCarga".
                    context["carga"] = None

                issue_date = extract_issue_date(text, recipient_cnpj)
                total_amount = extract_total_amount(text)
                nf_number = str(int(key[25:34]))
                series = str(int(key[22:25]))
                model = key[20:22]
                page_number = page_index + 1

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
                        issue_date=issue_date,
                        total_amount=total_amount,
                        pages=[page_number],
                        source_file=filename,
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
                    record.issue_date = record.issue_date or issue_date
                    record.total_amount = record.total_amount or total_amount
    finally:
        doc.close()

    return list(records_by_key.values())


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
    for (group_type, carga, cnpj, bucket_issuer_cnpj, name), invoices in buckets.items():
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
