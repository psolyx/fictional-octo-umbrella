from __future__ import annotations


def validate_profile_field(kind: str, value: str) -> str:
    text = value or ""
    if kind == "username":
        if len(text) < 1 or len(text) > 32:
            return "username_invalid_length: must be 1..32 chars"
        if "\n" in text:
            return "username_invalid_newline: must not contain newline"
        return ""
    if kind in {"description", "interests"}:
        if len(text) > 1024:
            return f"{kind}_too_long: max 1024 chars"
        return ""
    if kind in {"avatar", "banner"}:
        if not text:
            return ""
        lower = text.lower()
        if lower.startswith("http://") or lower.startswith("https://") or lower.startswith("data:image/"):
            return ""
        return f"{kind}_invalid_scheme: use http(s) or data:image/*"
    return ""
