"""Unicode-aware person-name parsing and conservative identity matching."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .common import clean

HONORIFIC_RE = re.compile(r"^(?:dr|prof|professor|mr|mrs|ms)\.?\s+", re.I)
CREDENTIAL_RE = re.compile(
    r",?\s+(?:ph\.?d\.?|m\.?d\.?|professor|associate professor|assistant professor).*$",
    re.I,
)
ROLE_SUFFIX_RE = re.compile(
    r",\s*(?:(?:co[- ]?)?c\.?\s*e\.?\s*o\.?|chief\b|(?:executive\s+|vice\s+)?president\b|"
    r"(?:co[- ]?)?founder\b|"
    r"chair(?:man|woman|person)?\b|(?:executive\s+)?director\b).*$",
    re.I,
)
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
BLOCKED_NAME_PHRASES = {
    "administrative staff",
    "associated faculty",
    "faculty",
    "faculty home page",
    "faculty profile",
    "in memoriam",
    "people",
    "read bio",
    "read more",
    "research staff",
    "staff",
    "technical staff",
    "view profile",
}
BLOCKED_NAME_WORDS = {
    "administration",
    "board",
    "department",
    "directors",
    "faculty",
    "leadership",
    "management",
    "office",
    "staff",
    "team",
}


@dataclass(frozen=True)
class NameParts:
    """The identity-bearing parts used for conservative name comparison."""

    given: str
    middle: tuple[str, ...]
    family: str
    suffix: str = ""

    @property
    def valid(self) -> bool:
        return bool(self.given and self.family)


def _token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold().replace("’", "'"))
    return "".join(character for character in normalized if character.isalnum())


def clean_person_name(value: str) -> str:
    """Remove presentation-only titles while retaining identity suffixes."""

    value = clean(value)
    for separator in (" | ", " - ", " – ", " — ", ":"):
        if separator in value:
            value = value.split(separator, 1)[0]
    value = HONORIFIC_RE.sub("", value)
    value = CREDENTIAL_RE.sub("", value)
    value = ROLE_SUFFIX_RE.sub("", value)

    if value.count(",") == 1:
        left, right = [clean(part) for part in value.split(",", 1)]
        if _token(right.rstrip(".")) in SUFFIXES:
            value = f"{left} {right}"
        elif left and right:
            right_words = right.split()
            if right_words and _token(right_words[-1].rstrip(".")) in SUFFIXES:
                suffix = right_words.pop()
                value = f"{' '.join(right_words)} {left} {suffix}"
            else:
                value = f"{right} {left}"
    return clean(value.strip(" ,"))


def parse_person_name(value: str) -> NameParts:
    """Parse first, family, and generational suffix without guessing identity."""

    cleaned = clean_person_name(value)
    raw_words = cleaned.split()
    if len(raw_words) < 2:
        return NameParts("", (), "", "")

    suffix = ""
    if _token(raw_words[-1].rstrip(".")) in SUFFIXES:
        suffix = _token(raw_words.pop().rstrip("."))
    if len(raw_words) < 2:
        return NameParts("", (), "", suffix)

    normalized = [_token(word) for word in raw_words]
    if any(not word for word in normalized):
        return NameParts("", (), "", suffix)

    # Treat spaced initials such as "C. C. Wei" the same as "C.C. Wei".
    leading_initials: list[str] = []
    while len(normalized) - len(leading_initials) > 1:
        word = normalized[len(leading_initials)]
        if len(word) != 1:
            break
        leading_initials.append(word)
    if leading_initials:
        given = "".join(leading_initials)
        middle = tuple(normalized[len(leading_initials) : -1])
    else:
        given = normalized[0]
        middle = tuple(normalized[1:-1])
    return NameParts(given, middle, normalized[-1], suffix)


def looks_like_person_name(value: str) -> bool:
    cleaned = clean_person_name(value)
    if cleaned.casefold() in BLOCKED_NAME_PHRASES:
        return False
    words = cleaned.split()
    if not 2 <= len(words) <= 7:
        return False
    if any(_token(word) in BLOCKED_NAME_WORDS for word in words):
        return False
    allowed_punctuation = {"'", "’", ".", "-"}
    return all(
        word and all(character.isalpha() or character in allowed_punctuation for character in word)
        for word in words
    )


def names_match(observed: str, expected: str) -> bool:
    """Require exact given/family identity and exact generational suffix state."""

    left = parse_person_name(observed)
    right = parse_person_name(expected)
    if not left.valid or not right.valid:
        return False
    return left.given == right.given and left.family == right.family and left.suffix == right.suffix


__all__ = [
    "NameParts",
    "clean_person_name",
    "looks_like_person_name",
    "names_match",
    "parse_person_name",
]
