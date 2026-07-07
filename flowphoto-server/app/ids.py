"""
Короткие ID: 12 символов, криптографически случайные (без путаницы 0/O, 1/l).
"""
import secrets

# 58 символов — удобно для URL и ручного ввода
_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def generate_short_id(length: int = 12) -> str:
    """Генерирует short_id заданной длины (по умолчанию 12)."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def is_valid_short_id(short_id: str) -> bool:
    """Проверка формата ID из URL."""
    return (
        isinstance(short_id, str)
        and len(short_id) == 12
        and all(c in _ID_ALPHABET for c in short_id)
    )