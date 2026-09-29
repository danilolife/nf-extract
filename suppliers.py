from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize(value: str | None) -> str:
    raw = (value or "").upper()
    return "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")


@dataclass(frozen=True)
class SupplierProfile:
    id: str
    display_name: str
    cnpjs: tuple[str, ...]
    aliases: tuple[str, ...]
    uses_carga: bool
    carga_patterns: tuple[str, ...]
    volume_patterns: tuple[str, ...]
    volume_mode: str

    @property
    def cnpj_digits(self) -> set[str]:
        return {digits_only(cnpj) for cnpj in self.cnpjs}


_CONFIG_PATH = Path(__file__).with_name("suppliers.json")


def load_supplier_profiles() -> list[SupplierProfile]:
    payload = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    profiles: list[SupplierProfile] = []
    for item in payload.get("suppliers", []):
        profiles.append(
            SupplierProfile(
                id=item["id"],
                display_name=item["display_name"],
                cnpjs=tuple(item.get("cnpjs", [])),
                aliases=tuple(item.get("aliases", [])),
                uses_carga=bool(item.get("uses_carga", False)),
                carga_patterns=tuple(item.get("carga_patterns", [])),
                volume_patterns=tuple(item.get("volume_patterns", [])),
                volume_mode=item.get("volume_mode", "per_invoice"),
            )
        )
    return profiles


SUPPLIER_PROFILES = load_supplier_profiles()


def get_supplier_profile(issuer_cnpj: str | None = None, issuer_name: str | None = None) -> SupplierProfile | None:
    cnpj_digits = digits_only(issuer_cnpj)
    if cnpj_digits:
        for profile in SUPPLIER_PROFILES:
            if cnpj_digits in profile.cnpj_digits:
                return profile

    normalized_name = normalize(issuer_name)
    if normalized_name:
        for profile in SUPPLIER_PROFILES:
            aliases = {normalize(profile.display_name), *(normalize(alias) for alias in profile.aliases)}
            if any(alias and alias in normalized_name for alias in aliases):
                return profile
    return None


def supplier_display_name(issuer_cnpj: str | None, detected_name: str | None) -> str | None:
    profile = get_supplier_profile(issuer_cnpj, detected_name)
    return profile.display_name if profile else detected_name


def extract_supplier_carga(text: str, issuer_cnpj: str | None, issuer_name: str | None) -> str | None:
    profile = get_supplier_profile(issuer_cnpj, issuer_name)
    if not profile or not profile.uses_carga:
        return None
    patterns = profile.carga_patterns or (r"\b(?:NRO\s*)?CARGA\s*:?\s*(\d{2,})\b",)
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def supplier_uses_carga(issuer_cnpj: str | None, issuer_name: str | None) -> bool:
    profile = get_supplier_profile(issuer_cnpj, issuer_name)
    return bool(profile and profile.uses_carga)


def extract_supplier_volume(text: str, issuer_cnpj: str | None, issuer_name: str | None) -> int | None:
    profile = get_supplier_profile(issuer_cnpj, issuer_name)
    if not profile:
        return None
    for pattern in profile.volume_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if 0 < value < 10_000_000:
                return value
    return None


def serialize_supplier_profiles() -> list[dict]:
    return [
        {
            "id": profile.id,
            "display_name": profile.display_name,
            "cnpjs": list(profile.cnpjs),
            "aliases": list(profile.aliases),
            "uses_carga": profile.uses_carga,
            "volume_patterns": list(profile.volume_patterns),
            "volume_mode": profile.volume_mode,
        }
        for profile in SUPPLIER_PROFILES
    ]
