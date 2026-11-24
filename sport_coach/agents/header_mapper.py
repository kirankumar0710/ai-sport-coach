"""Header Mapper Agent: maps a user's column headers onto the app template.

Structured output: the model must answer with HeaderMappingResult JSON. It only
names columns and units; the values are converted in Python (sport_coach.ingest).
"""

import json
from typing import Literal

from google.adk.agents import LlmAgent
from pydantic import BaseModel, Field

from sport_coach.config import Settings
from sport_coach.ingest import UNIT_FACTORS
from sport_coach.llm.factory import build_generation_config, build_model
from sport_coach.schema import COLUMNS, TEMPLATE

TemplateFieldName = Literal[tuple(COLUMNS)]  # type: ignore[valid-type]


class FieldMatch(BaseModel):
    field: TemplateFieldName = Field(description="Template field name.")
    column: str = Field(description="The user's header, copied exactly.")
    unit: str = Field(default="", description="Source unit from the allowed list, or empty.")


class HeaderMappingResult(BaseModel):
    matches: list[FieldMatch] = Field(description="One entry per template field that has a matching column.")
    date_order: Literal["day-first", "month-first", "unknown"] = Field(
        default="unknown", description="Order of ambiguous dates like 03/04/2026."
    )


def _template_description() -> str:
    lines = []
    for f in TEMPLATE:
        units = list(UNIT_FACTORS.get(f.name, {}))
        unit_text = f" Allowed units: {', '.join(units)}." if units else ""
        lines.append(f"- {f.name}: {f.description}{unit_text}")
    return "\n".join(lines)


INSTRUCTION = f"""\
You map the columns of a user's workout file onto our template.

Template fields:
{_template_description()}

You get the user's headers and a few sample rows. Return the matches:
- Match by meaning, in any language or abbreviation ("Strecke", "Dist.", "Dauer", "Kcal").
- Use the sample values to decide (e.g. which column holds dates, which holds distances).
- Copy the header text exactly as given. Use each column at most once.
- Leave a field out when no column clearly matches. Never guess.
- unit: pick from the allowed units using the header and values. For duration use
  "clock" when values look like h:mm:ss or mm:ss. Leave empty for fields without units.
- date_order: "day-first" or "month-first" if the sample dates show it, else "unknown".
"""


def build_header_mapper_agent(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="header_mapper",
        description="Maps user workout-file headers onto the app template.",
        model=build_model(settings.provider),
        # temperature 0 where the provider allows it; dropped otherwise (see factory)
        generate_content_config=build_generation_config(settings.provider, temperature=0),
        instruction=INSTRUCTION,
        output_schema=HeaderMappingResult,
    )


def mapper_input(headers: list[str], sample_rows: list[list[str]]) -> str:
    return json.dumps({"headers": headers, "sample_rows": sample_rows}, ensure_ascii=False)


def parse_mapper_output(text: str) -> dict:
    """Model JSON -> the dict shape sport_coach.ingest expects. Raises on bad output."""
    text = text.strip()
    if text.startswith("```"):  # tolerate fenced JSON from some providers
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    result = HeaderMappingResult.model_validate_json(text)
    return {
        "columns": {m.field: m.column for m in result.matches},
        "units": {m.field: m.unit for m in result.matches if m.unit},
        "date_order": result.date_order if result.date_order != "unknown" else None,
    }
