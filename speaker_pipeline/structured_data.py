"""Bounded JSON-LD extraction for official person-profile pages."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .common import clean

MAX_JSONLD_SCRIPTS = 50
MAX_JSONLD_CHARACTERS = 1_000_000
MAX_JSONLD_DEPTH = 12


@dataclass(frozen=True)
class StructuredPerson:
    name: str
    title: str = ""
    email: str = ""
    url: str = ""
    description: str = ""


def _walk(value: object, depth: int = 0) -> Iterator[dict[str, object]]:
    if depth > MAX_JSONLD_DEPTH:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, depth + 1)


def _types(node: dict[str, object]) -> set[str]:
    value = node.get("@type", "")
    values = value if isinstance(value, list) else [value]
    output: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not clean(item):
            continue
        normalized = clean(item).casefold()
        output.add(_terminal_type(normalized))
    return output


def _terminal_type(value: str) -> str:
    """Return the terminal JSON-LD type from compact or absolute IRIs."""

    for separator in ("#", "/", ":"):
        value = value.rsplit(separator, 1)[-1]
    return value


def _scalar(value: object) -> str:
    if isinstance(value, list):
        return clean(next((item for item in value if isinstance(item, str) and clean(item)), ""))
    return clean(value) if isinstance(value, (str, int, float)) else ""


def iter_jsonld_nodes(soup: BeautifulSoup) -> Iterator[dict[str, object]]:
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts[:MAX_JSONLD_SCRIPTS]:
        payload = script.string if script.string is not None else script.get_text()
        payload = payload.strip()
        if not payload or len(payload) > MAX_JSONLD_CHARACTERS:
            continue
        if payload.startswith("<!--") and payload.endswith("-->"):
            payload = payload[4:-3].strip()
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            continue
        yield from _walk(value)


def extract_structured_people(soup: BeautifulSoup) -> list[StructuredPerson]:
    people: list[StructuredPerson] = []
    seen: set[tuple[str, str, str]] = set()
    for node in iter_jsonld_nodes(soup):
        if "person" not in _types(node):
            continue
        name = _scalar(node.get("name"))
        if not name:
            continue
        email = _scalar(node.get("email"))
        if email.casefold().startswith("mailto:"):
            email = email[7:].split("?", 1)[0]
        person = StructuredPerson(
            name=name,
            title=_scalar(node.get("jobTitle")),
            email=clean(email),
            url=_scalar(node.get("url")),
            description=_scalar(node.get("description")),
        )
        key = (person.name.casefold(), person.title.casefold(), person.email.casefold())
        if key not in seen:
            seen.add(key)
            people.append(person)
    return people


__all__ = ["StructuredPerson", "extract_structured_people", "iter_jsonld_nodes"]
