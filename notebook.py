"""Pipeline Colab para curadoria de conteúdo do Harn Flex.

Uso no Colab:
    1. Faça upload de Relatorio.md.
    2. Configure SPREADSHEETS_ID nos Secrets.
    3. Execute run_pipeline().

O módulo também pode ser importado e testado localmente sem Google APIs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SOURCE_FILENAME = "Relatorio.md"
CONTENT_SHEETS = ("Species", "Glossary", "Content")

CONCEPT_TERMS = {
    "bergmann": ("regra de bergmann", "bergmann"),
    "allen": ("regra de allen", "allen"),
    "protecao_ocular": ("proteção ocular", "protecao ocular"),
    "convergencia_funcional": (
        "convergência funcional",
        "convergencia funcional",
    ),
    "superficie_volume": (
        "superfície/volume",
        "superficie/volume",
        "superfície-volume",
    ),
    "plasticidade": ("plasticidade",),
    "hipoxia_altitude": ("hipóxia", "hipoxia", "altitude"),
    "aridez": ("aridez", "árido", "arido"),
    "radiacao": ("radiação", "radiacao"),
    "trade_off_energetico": (
        "trade-off energético",
        "trade off energético",
        "trade-off energetico",
    ),
    "mismatch_ecologico": (
        "mismatch ecológico",
        "mismatch ecologico",
        "desajuste ecológico",
    ),
    "excecao_de_nicho": ("exceção de nicho", "excecao de nicho"),
}

# O catálogo só identifica menções. Descrição, bioma e traços continuam vindo
# do relatório, evitando transformar conhecimento embutido no código em fonte.
SPECIES_CATALOG = {
    "urso-polar": {
        "common_name": "Urso-polar",
        "scientific_name": "Ursus maritimus",
        "aliases": ("urso-polar", "urso polar", "ursus maritimus"),
    },
    "urso-de-oculos": {
        "common_name": "Urso-de-óculos",
        "scientific_name": "Tremarctos ornatus",
        "aliases": (
            "urso-de-óculos",
            "urso de óculos",
            "urso-de-oculos",
            "tremarctos ornatus",
        ),
    },
    "leopardo-das-neves": {
        "common_name": "Leopardo-das-neves",
        "scientific_name": "Panthera uncia",
        "aliases": (
            "leopardo-das-neves",
            "leopardo das neves",
            "panthera uncia",
        ),
    },
    "leopardo": {
        "common_name": "Leopardo",
        "scientific_name": "Panthera pardus",
        "aliases": ("leopardo comum", "panthera pardus"),
    },
    "camelo-bactriano": {
        "common_name": "Camelo-bactriano",
        "scientific_name": "Camelus bactrianus",
        "aliases": (
            "camelo-bactriano",
            "camelo bactriano",
            "bactriano",
            "camelus bactrianus",
        ),
    },
    "dromedario": {
        "common_name": "Dromedário",
        "scientific_name": "Camelus dromedarius",
        "aliases": ("dromedário", "dromedario", "camelus dromedarius"),
    },
    "cavalo-de-przewalski": {
        "common_name": "Cavalo-de-Przewalski",
        "scientific_name": "Equus ferus przewalskii",
        "aliases": (
            "przewalski",
            "cavalo-de-przewalski",
            "equus ferus przewalskii",
        ),
    },
    "puma": {
        "common_name": "Puma",
        "scientific_name": "Puma concolor",
        "aliases": ("puma", "onça-parda", "onca-parda", "puma concolor"),
    },
}


@dataclass(frozen=True)
class MarkdownSection:
    level: int
    title: str
    body: str
    order: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_marks.lower()).strip()


def parse_markdown_sections(markdown: str) -> list[MarkdownSection]:
    """Divide Markdown por headings ATX, ignorando headings em code fences."""
    sections: list[MarkdownSection] = []
    current_title = "Introdução"
    current_level = 1
    body_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(body_lines).strip()
        if body:
            sections.append(
                MarkdownSection(
                    level=current_level,
                    title=current_title,
                    body=body,
                    order=len(sections) + 1,
                )
            )

    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            body_lines.append(line)
            continue

        match = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            current_level = len(match.group(1))
            current_title = re.sub(r"\s+#+$", "", match.group(2)).strip()
            body_lines = []
        else:
            body_lines.append(line)

    flush()
    return sections


def concepts_in_text(text: str) -> list[str]:
    normalized = normalize_text(text)
    found = []
    for concept, terms in CONCEPT_TERMS.items():
        if any(normalize_text(term) in normalized for term in terms):
            found.append(concept)
    return found


def excerpt(text: str, max_length: int = 700) -> str:
    plain = re.sub(r"\s+", " ", re.sub(r"[`*_>#-]", " ", text)).strip()
    if len(plain) <= max_length:
        return plain
    shortened = plain[: max_length - 1].rsplit(" ", 1)[0]
    return shortened + "…"


def build_content_rows(
    sections: Sequence[MarkdownSection],
    source: str = SOURCE_FILENAME,
) -> list[dict[str, Any]]:
    now = utc_now()
    rows = []
    for section in sections:
        concepts = concepts_in_text(f"{section.title}\n{section.body}")
        natural_key = f"{source}:{section.order}:{section.title}"
        rows.append(
            {
                "content_id": stable_id("content", natural_key),
                "title": section.title,
                "body": section.body,
                "content_type": "article",
                "created_at": now,
                "section": section.title,
                "sort_order": section.order,
                "concept": ",".join(concepts),
                "source": source,
            }
        )
    return rows


def build_glossary_rows(
    sections: Sequence[MarkdownSection],
    source: str = SOURCE_FILENAME,
) -> list[dict[str, Any]]:
    now = utc_now()
    candidates: dict[str, dict[str, Any]] = {}
    for section in sections:
        section_text = f"{section.title}\n{section.body}"
        for concept in concepts_in_text(section_text):
            candidates.setdefault(
                concept,
                {
                    "term_id": stable_id("term", concept),
                    "term": concept.replace("_", " ").title(),
                    "definition": excerpt(section.body),
                    "category": "ecomorfologia",
                    "created_at": now,
                    "concept": concept,
                    "source": source,
                },
            )
    return list(candidates.values())


CONCEPT_LABELS = {key: key.replace("_", " ").title() for key in CONCEPT_TERMS}


def build_question_rows(
    sections: Sequence[MarkdownSection],
    source: str = SOURCE_FILENAME,
) -> list[dict[str, Any]]:
    """Gera perguntas de reconhecimento de conceito a partir do relatório.

    Cada conceito presente no texto vira uma pergunta cuja alternativa correta é
    o nome do conceito e cujo enunciado é um trecho real (excerpt) do relatório.
    Nada de fatos inventados: o conteúdo deriva das seções; só o enquadramento
    ("a descrição está associada a qual conceito?") é estrutural. Determinístico
    (idempotente no upsert por question_id).
    """
    now = utc_now()

    # Conceito -> melhor definição (primeiro trecho do relatório que o menciona).
    definitions: dict[str, str] = {}
    for section in sections:
        text = f"{section.title}\n{section.body}"
        for concept in concepts_in_text(text):
            if concept not in definitions:
                definitions[concept] = excerpt(section.body, 320)

    concepts = list(definitions.keys())
    if len(concepts) < 2:
        return []

    letters = ["a", "b", "c", "d"]
    rows = []
    for concept in concepts:
        correct_label = CONCEPT_LABELS[concept]
        others = [CONCEPT_LABELS[c] for c in CONCEPT_TERMS if c != concept]
        seed = int(hashlib.sha256(concept.encode("utf-8")).hexdigest(), 16)
        distractors = [others[(seed + k) % len(others)] for k in range(min(3, len(others)))]

        ordered: list[str | None] = [None, None, None, None]
        correct_idx = seed % 4
        ordered[correct_idx] = correct_label
        di = 0
        for slot in range(4):
            if ordered[slot] is None and di < len(distractors):
                ordered[slot] = distractors[di]
                di += 1

        rows.append(
            {
                "question_id": stable_id("question", f"concept:{concept}"),
                "quiz_id": "pool",
                "question_text": (
                    "A descrição a seguir está mais associada a qual conceito? "
                    f"“{definitions[concept]}”"
                ),
                "option_a": ordered[0] or "",
                "option_b": ordered[1] or "",
                "option_c": ordered[2] or "",
                "option_d": ordered[3] or "",
                "correct_answer": letters[correct_idx],
                "explanation": (
                    f"O trecho tende a descrever {correct_label}. Leia com cautela: "
                    "padrões sugerem tendências, com exceções de nicho."
                ),
                "difficulty": "medium",
                "concept": concept,
                "created_at": now,
            }
        )
    return rows


def build_species_rows(
    sections: Sequence[MarkdownSection],
    source: str = SOURCE_FILENAME,
) -> list[dict[str, Any]]:
    now = utc_now()
    rows = []
    normalized_sections = [
        (section, normalize_text(f"{section.title}\n{section.body}"))
        for section in sections
    ]

    for slug, species in SPECIES_CATALOG.items():
        matching = [
            section
            for section, normalized in normalized_sections
            if any(normalize_text(alias) in normalized for alias in species["aliases"])
        ]
        if not matching:
            continue

        combined = "\n\n".join(section.body for section in matching)
        rows.append(
            {
                "species_id": stable_id("species", slug),
                "common_name": species["common_name"],
                "scientific_name": species["scientific_name"],
                "description": excerpt(combined),
                "image_url": "",
                "created_at": now,
                "lineage": "",
                "biome": "",
                "ecological_pressure": "",
                "traits": ",".join(concepts_in_text(combined)),
                "source": source,
            }
        )
    return rows


def build_dataset(markdown: str, source: str = SOURCE_FILENAME) -> dict[str, list]:
    sections = parse_markdown_sections(markdown)
    if not sections:
        raise ValueError("O relatório não contém seções com conteúdo.")
    return {
        "Content": build_content_rows(sections, source),
        "Glossary": build_glossary_rows(sections, source),
        "Species": build_species_rows(sections, source),
        "Questions": build_question_rows(sections, source),
    }


def authenticate_colab() -> None:
    try:
        from google.colab import auth  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Autenticação Colab disponível apenas no Colab.") from exc
    auth.authenticate_user()


def get_secret(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name)
    try:
        from google.colab import userdata  # type: ignore

        value = value or userdata.get(name)
    except (ImportError, KeyError):
        pass
    if required and not value:
        raise RuntimeError(f"Secret obrigatório ausente: {name}")
    return value


def connect_spreadsheet(spreadsheet_id: str | None = None):
    try:
        import gspread  # type: ignore
        from google.auth import default  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Instale gspread e google-auth no ambiente.") from exc

    credentials, _ = default()
    client = gspread.authorize(credentials)
    return client.open_by_key(spreadsheet_id or get_secret("SPREADSHEETS_ID"))


def ensure_worksheet(spreadsheet, title: str, headers: Sequence[str]):
    try:
        worksheet = spreadsheet.worksheet(title)
    except Exception as exc:
        if exc.__class__.__name__ != "WorksheetNotFound":
            raise
        worksheet = spreadsheet.add_worksheet(
            title=title,
            rows=1000,
            cols=max(10, len(headers)),
        )

    existing = worksheet.row_values(1)
    missing = [header for header in headers if header not in existing]
    if not existing:
        worksheet.update([list(headers)], "A1")
    elif missing:
        start = len(existing) + 1
        worksheet.update([missing], rowcol_to_a1(1, start))
    return worksheet


def rowcol_to_a1(row: int, column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def upsert_records(
    worksheet,
    records: Sequence[Mapping[str, Any]],
    key_column: str,
) -> dict[str, int]:
    if not records:
        return {"inserted": 0, "updated": 0}

    headers = worksheet.row_values(1)
    if key_column not in headers:
        raise ValueError(f"Coluna-chave ausente em {worksheet.title}: {key_column}")

    existing = worksheet.get_all_records(default_blank="")
    positions = {
        str(record.get(key_column, "")): index + 2
        for index, record in enumerate(existing)
        if record.get(key_column, "") != ""
    }
    inserted = 0
    updated = 0

    for record in records:
        key = str(record.get(key_column, ""))
        if not key:
            raise ValueError(f"Registro sem {key_column}: {record}")
        row = [record.get(header, "") for header in headers]
        if key in positions:
            worksheet.update([row], rowcol_to_a1(positions[key], 1))
            updated += 1
        else:
            worksheet.append_row(row, value_input_option="RAW")
            positions[key] = len(positions) + 2
            inserted += 1

    return {"inserted": inserted, "updated": updated}


def seed_dataset(spreadsheet, dataset: Mapping[str, Sequence[Mapping]]) -> dict:
    definitions = {
        "Species": ("species_id", list(dataset.get("Species", [{}])[0].keys())
                    if dataset.get("Species") else [
                        "species_id", "common_name", "scientific_name",
                        "description", "image_url", "created_at", "lineage",
                        "biome", "ecological_pressure", "traits", "source",
                    ]),
        "Glossary": ("term_id", list(dataset.get("Glossary", [{}])[0].keys())
                     if dataset.get("Glossary") else [
                         "term_id", "term", "definition", "category",
                         "created_at", "concept", "source",
                     ]),
        "Content": ("content_id", list(dataset.get("Content", [{}])[0].keys())
                    if dataset.get("Content") else [
                        "content_id", "title", "body", "content_type",
                        "created_at", "section", "sort_order", "concept", "source",
                    ]),
        "Questions": ("question_id", list(dataset.get("Questions", [{}])[0].keys())
                      if dataset.get("Questions") else [
                          "question_id", "quiz_id", "question_text",
                          "option_a", "option_b", "option_c", "option_d",
                          "correct_answer", "explanation", "difficulty",
                          "concept", "created_at",
                      ]),
    }
    report = {}
    for sheet_name, (key, headers) in definitions.items():
        worksheet = ensure_worksheet(spreadsheet, sheet_name, headers)
        report[sheet_name] = upsert_records(
            worksheet,
            dataset.get(sheet_name, []),
            key,
        )
    return report


def backup_sheets(
    spreadsheet,
    output_dir: str | Path = "backups",
    sheet_names: Iterable[str] = CONTENT_SHEETS,
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = []

    for sheet_name in sheet_names:
        values = spreadsheet.worksheet(sheet_name).get_all_values()
        path = output / f"{sheet_name}_{timestamp}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            csv.writer(handle).writerows(values)
        paths.append(path)
    return paths


def call_health_check(webapp_url: str | None = None) -> dict:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Instale requests para consultar o Web App.") from exc

    base_url = webapp_url or get_secret("APPS_SCRIPT_WEBAPP_URL")
    response = requests.get(
        base_url,
        params={"route": "auth/health"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def run_pipeline(
    report_path: str | Path = SOURCE_FILENAME,
    create_backup: bool = True,
) -> dict[str, Any]:
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} não encontrado. Faça upload do relatório antes da semeadura."
        )

    markdown = path.read_text(encoding="utf-8")
    dataset = build_dataset(markdown, path.name)
    authenticate_colab()
    spreadsheet = connect_spreadsheet()
    seed_report = seed_dataset(spreadsheet, dataset)
    backups = backup_sheets(spreadsheet) if create_backup else []
    return {
        "source": path.name,
        "records": {name: len(rows) for name, rows in dataset.items()},
        "seed": seed_report,
        "backups": [str(path) for path in backups],
    }


if __name__ == "__main__":
    print(json.dumps(run_pipeline(), ensure_ascii=False, indent=2))
