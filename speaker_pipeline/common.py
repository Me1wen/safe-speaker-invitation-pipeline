"""Shared table, identity, URL, and merge helpers."""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .schema import CANDIDATE_COLUMNS, CANDIDATE_STATUSES

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def today_iso() -> str:
    return date.today().isoformat()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_name(value: str) -> str:
    value = re.sub(r"\b(?:dr|prof|professor|mr|mrs|ms)\.?\b", "", clean(value), flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def normalize_url(value: str) -> str:
    parsed = urlparse(clean(value))
    if not parsed.scheme or not parsed.netloc:
        return clean(value)
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    host = parsed.netloc.casefold().removeprefix("www.")
    return f"{parsed.scheme.casefold()}://{host}{path}"


def candidate_id(speaker_type: str, name: str, organization: str) -> str:
    normalized = (
        f"{speaker_type.casefold()}|{normalize_name(name)}|{clean(organization).casefold()}"
    )
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()
    prefix = "ACAD" if speaker_type.casefold() == "academic" else "IND"
    return f"{prefix}-{digest}"


def draft_id(candidate_id_value: str, subject: str, body: str) -> str:
    digest = hashlib.sha256(f"{candidate_id_value}|{subject}|{body}".encode()).hexdigest()
    return f"DRAFT-{digest[:16].upper()}"


def split_domains(value: str, fallback: str = "") -> tuple[str, ...]:
    values = [*re.split(r"[;,\s]+", clean(value)), fallback]
    domains: set[str] = set()
    for item in values:
        item = clean(item).casefold()
        if not item:
            continue
        parsed = urlparse(item if "://" in item else f"https://{item}")
        host = parsed.hostname or ""
        if host:
            domains.add(host.removeprefix("www."))
    return tuple(sorted(domains))


def host_allowed(url: str, domains: Iterable[str]) -> bool:
    parsed = urlparse(clean(url))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    return parsed.scheme in {"http", "https"} and any(
        host == domain or host.endswith(f".{domain}") for domain in domains
    )


def email_allowed(email: str, domains: Iterable[str]) -> bool:
    if not EMAIL_RE.fullmatch(clean(email)):
        return False
    host = clean(email).rsplit("@", 1)[-1].casefold().removeprefix("www.")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def read_csv(path: Path, expected: list[str] | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if expected is not None and headers != expected:
            raise ValueError(f"{path} columns do not match the required schema. Found: {headers}")
        return [{key: clean(value) for key, value in row.items() if key} for row in reader]


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    temporary.replace(path)


def read_table(
    path: Path, columns: list[str], sheet_name: str | None = None
) -> list[dict[str, str]]:
    if path.suffix.casefold() == ".csv":
        return read_csv(path, columns)
    if path.suffix.casefold() not in {".xlsx", ".xlsm"}:
        raise ValueError("Input must be CSV, XLSX, or XLSM.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"Sheet not found: {sheet_name}")
            worksheet = workbook[sheet_name]
        elif len(workbook.sheetnames) == 1:
            worksheet = workbook.active
        else:
            raise ValueError("Workbook has multiple sheets; provide a sheet name.")
        values = worksheet.iter_rows(values_only=True)
        headers = [clean(value) for value in next(values, ())]
        if headers != columns:
            raise ValueError(f"Workbook columns do not match the required schema. Found: {headers}")
        rows: list[dict[str, str]] = []
        for values_row in values:
            row = {header: clean(value) for header, value in zip(headers, values_row, strict=False)}
            if any(row.values()):
                rows.append(row)
        return rows
    finally:
        workbook.close()


def write_workbook(
    path: Path, sheet_name: str, columns: list[str], rows: Iterable[dict[str, object]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name
    worksheet.freeze_panes = "A2"
    worksheet.sheet_view.showGridLines = False
    worksheet.append(columns)
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in rows:
        worksheet.append([row.get(column, "") for column in columns])
    for column_cells in worksheet.columns:
        width = max(len(clean(cell.value)) for cell in column_cells)
        worksheet.column_dimensions[column_cells[0].column_letter].width = min(
            max(width + 2, 12), 60
        )
    worksheet.auto_filter.ref = worksheet.dimensions
    workbook.save(path)


def candidate_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        clean(row.get("Speaker Type")).casefold(),
        normalize_name(row.get("Full Name", "")),
        clean(row.get("Organization")).casefold(),
    )


def merge_candidates(
    existing: Iterable[dict[str, str]],
    discovered: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    """Merge without overwriting any manually approved record."""
    merged: list[dict[str, str]] = []
    by_key: dict[tuple[str, str, str], int] = {}
    by_url: dict[str, int] = {}

    for source_row in existing:
        row = {column: clean(source_row.get(column, "")) for column in CANDIDATE_COLUMNS}
        if row["Review Status"] not in CANDIDATE_STATUSES:
            raise ValueError(f"Invalid Review Status: {row['Review Status']}")
        index = len(merged)
        merged.append(row)
        key = candidate_key(row)
        if all(key):
            by_key[key] = index
        if row["Profile URL"]:
            by_url[normalize_url(row["Profile URL"])] = index

    manual_fields = {"Review Status", "Topic Fit", "Preferred Salutation", "Notes"}
    for source_row in discovered:
        row = {column: clean(source_row.get(column, "")) for column in CANDIDATE_COLUMNS}
        key = candidate_key(row)
        url_key = normalize_url(row["Profile URL"])
        index = by_key.get(key) if all(key) else None
        if index is None and url_key:
            index = by_url.get(url_key)
        if index is None:
            index = len(merged)
            merged.append(row)
        else:
            old = merged[index]
            if old.get("Review Status") != "Approved":
                combined = dict(old)
                for column in CANDIDATE_COLUMNS:
                    if column not in manual_fields and row.get(column):
                        combined[column] = row[column]
                for column in manual_fields:
                    combined[column] = old.get(column) or row.get(column, "")
                merged[index] = combined
        final = merged[index]
        final["Candidate ID"] = final.get("Candidate ID") or candidate_id(
            final.get("Speaker Type", ""), final.get("Full Name", ""), final.get("Organization", "")
        )
        final["Review Status"] = final.get("Review Status") or "Draft"
        final["Last Checked"] = final.get("Last Checked") or today_iso()
        final_key = candidate_key(final)
        if all(final_key):
            by_key[final_key] = index
        if final.get("Profile URL"):
            by_url[normalize_url(final["Profile URL"])] = index
    return merged
