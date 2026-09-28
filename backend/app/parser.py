from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from io import BytesIO
from typing import Iterable

import fitz  # PyMuPDF

CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
CARGA_RE = re.compile(r"\bCARGA\s*:?\s*(\d{4,})\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
MONEY_RE = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b")


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
    issue_date: str | None = None
    total_amount: str | None = None
    pages: list[int] = field(default_factory=list)
    source_file: str | None = None


@dataclass
class GroupResult:
    carga: str
    recipient_cnpj: str
    recipient_name: str
    invoices: list[InvoiceRecord]

    @property
    def key_count(self) -> int:
        return len(self.invoices)


def digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


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
        window = text[match.end() : match.end() + 220]
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


def extract_recipient(text: str) -> tuple[str | None, str | None]:
    """Return (recipient_name, recipient_cnpj) from the destinatário section."""
    upper = text.upper()
    start = upper.find("DESTINATÁRIO/REMETENTE")
    if start == -1:
        start = upper.find("DESTINATARIO/REMETENTE")
    if start == -1:
        return None, None

    segment = text[start : start + 900]
    cnpjs = CNPJ_RE.findall(segment)
    if not cnpjs:
        return None, None
    recipient_cnpj = cnpjs[0]

    # Depending on the PDF generator, name and CNPJ may be on the same line or
    # on consecutive lines. Walk backwards from the CNPJ while ignoring field labels/dates.
    recipient_name = None
    lines = [line.strip() for line in segment.splitlines() if line.strip()]
    labels = {
        "NOME/RAZÃO SOCIAL", "NOME/RAZAO SOCIAL", "DATA DA EMISSÃO", "DATA DA EMISSAO",
        "CNPJ/CPF", "LOGRADOURO", "BAIRRO/DISTRITO", "DATA DA ENTRADA/SAÍDA",
        "DATA DA ENTRADA/SAIDA", "HORA DE SAÍDA", "HORA DE SAIDA", "INSCRIÇÃO ESTADUAL",
        "INSCRICAO ESTADUAL", "UF", "MUNICÍPIO", "MUNICIPIO", "TELEFONE/FAX", "CEP", "FATURA"
    }
    for index, line in enumerate(lines):
        if recipient_cnpj not in line:
            continue
        before = line.split(recipient_cnpj, 1)[0].strip(" -\t")
        if before and before.upper() not in labels:
            recipient_name = before
            break
        for previous in reversed(lines[:index]):
            up = previous.upper()
            if up in labels or DATE_RE.fullmatch(previous) or CNPJ_RE.fullmatch(previous):
                continue
            if re.fullmatch(r"[\d./:-]+", previous):
                continue
            recipient_name = previous
            break
        break

    return recipient_name, recipient_cnpj


def extract_issue_date(text: str, recipient_cnpj: str | None) -> str | None:
    # In DANFE text extraction the emission date can appear before the recipient name/CNPJ.
    upper = text.upper()
    start = upper.find("DESTINATÁRIO/REMETENTE")
    if start == -1:
        start = upper.find("DESTINATARIO/REMETENTE")
    if start != -1:
        segment = text[start : start + 900]
        dates = DATE_RE.findall(segment)
        if dates:
            return dates[0]
    dates = DATE_RE.findall(text)
    return dates[0] if dates else None


def extract_total_amount(text: str) -> str | None:
    # Receipt stub is a strong signal in DANFEs and usually exposes the invoice value near
    # "RECEBEMOS DE", even when the PDF text order differs visually from the page.
    receipt = re.search(r"RECEBEMOS\s+DE", text, flags=re.IGNORECASE)
    if receipt:
        window = text[receipt.start() : receipt.start() + 220]
        values = MONEY_RE.findall(window)
        if values:
            return values[0]

    # Fallback: look around the total section and choose the largest monetary value found.
    marker = re.search(r"VALOR\s+TOTAL\s+DA\s+NOTA", text, flags=re.IGNORECASE)
    if marker:
        window = text[marker.end() : marker.end() + 520]
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
    last_carga: str | None = None
    last_recipient_name: str | None = None
    last_recipient_cnpj: str | None = None

    try:
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            if not text.strip():
                continue

            carga_match = CARGA_RE.search(text)
            carga = carga_match.group(1) if carga_match else last_carga
            if carga:
                last_carga = carga

            recipient_name, recipient_cnpj = extract_recipient(text)
            if recipient_cnpj:
                last_recipient_cnpj = recipient_cnpj
                last_recipient_name = recipient_name or last_recipient_name
            else:
                recipient_cnpj = last_recipient_cnpj
                recipient_name = last_recipient_name

            keys = extract_access_keys(text)
            issue_date = extract_issue_date(text, recipient_cnpj)
            total_amount = extract_total_amount(text)

            for key in keys:
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
                        issue_date=issue_date,
                        total_amount=total_amount,
                        pages=[page_number],
                        source_file=filename,
                    )
                else:
                    record = records_by_key[key]
                    if page_number not in record.pages:
                        record.pages.append(page_number)
                    # Merge missing metadata from repeated/continuation pages.
                    record.carga = record.carga or carga
                    record.recipient_name = record.recipient_name or recipient_name
                    record.recipient_cnpj = record.recipient_cnpj or recipient_cnpj
                    record.issue_date = record.issue_date or issue_date
                    record.total_amount = record.total_amount or total_amount
    finally:
        doc.close()

    return list(records_by_key.values())


def group_records(records: Iterable[InvoiceRecord]) -> list[GroupResult]:
    buckets: dict[tuple[str, str, str], list[InvoiceRecord]] = defaultdict(list)
    for record in records:
        carga = record.carga or "SEM CARGA"
        cnpj = record.recipient_cnpj or "CNPJ NÃO IDENTIFICADO"
        name = record.recipient_name or "DESTINATÁRIO NÃO IDENTIFICADO"
        buckets[(carga, cnpj, name)].append(record)

    groups: list[GroupResult] = []
    for (carga, cnpj, name), invoices in buckets.items():
        invoices.sort(key=lambda x: (int(x.nf_number) if x.nf_number.isdigit() else 0, x.access_key))
        groups.append(GroupResult(carga=carga, recipient_cnpj=cnpj, recipient_name=name, invoices=invoices))

    groups.sort(key=lambda g: (g.carga, g.recipient_cnpj))
    return groups


def serialize_groups(groups: list[GroupResult]) -> list[dict]:
    payload: list[dict] = []
    for group in groups:
        payload.append(
            {
                "carga": group.carga,
                "recipient_cnpj": group.recipient_cnpj,
                "recipient_name": group.recipient_name,
                "key_count": group.key_count,
                "invoices": [asdict(invoice) for invoice in group.invoices],
            }
        )
    return payload
