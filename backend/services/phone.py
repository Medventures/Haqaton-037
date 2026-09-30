import re


def normalize_phone(raw: str) -> str:
    """Normalize a Kazakhstan mobile number to 7XXXXXXXXXX (11 digits, no plus)."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not re.fullmatch(r"7\d{10}", digits):
        raise ValueError("Введите номер в формате +7 XXX XXX XX XX")
    return digits
