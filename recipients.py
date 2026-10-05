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
    raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", raw).strip()


@dataclass(frozen=True)
class RecipientProfile:
    cnpj: str
    display_name: str
    aliases: tuple[str, ...]

    @property
    def cnpj_digits(self) -> str:
        return digits_only(self.cnpj)


_CONFIG_PATH = Path(__file__).with_name("recipients.json")


def load_recipient_profiles() -> list[RecipientProfile]:
    payload = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return [
        RecipientProfile(
            cnpj=item["cnpj"],
            display_name=item["display_name"],
            aliases=tuple(item.get("aliases", [])),
        )
        for item in payload.get("recipients", [])
    ]


RECIPIENT_PROFILES = load_recipient_profiles()


def get_recipient_profile(cnpj: str | None) -> RecipientProfile | None:
    target = digits_only(cnpj)
    if not target:
        return None
    for profile in RECIPIENT_PROFILES:
        if profile.cnpj_digits == target:
            return profile
    return None


def recipient_name_matches(profile: RecipientProfile | None, detected_name: str | None) -> bool | None:
    if not profile:
        return None
    detected = normalize(detected_name)
    if not detected:
        return False
    candidates = {normalize(profile.display_name), *(normalize(alias) for alias in profile.aliases)}
    return any(candidate and (candidate in detected or detected in candidate) for candidate in candidates)


def validate_recipient_against_registry(cnpj: str | None, detected_name: str | None) -> tuple[bool, str | None, bool | None]:
    profile = get_recipient_profile(cnpj)
    if not profile:
        return False, None, None
    return True, profile.display_name, recipient_name_matches(profile, detected_name)


def serialize_recipient_profiles() -> list[dict]:
    return [
        {
            "cnpj": profile.cnpj,
            "display_name": profile.display_name,
            "aliases": list(profile.aliases),
        }
        for profile in RECIPIENT_PROFILES
    ]
