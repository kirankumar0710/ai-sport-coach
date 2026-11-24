from pathlib import Path

import pytest
from google.adk.tools.function_tool import FunctionTool
from pydantic import ValidationError

from sport_coach.agents.header_mapper import parse_mapper_output
from sport_coach.tools.workout_tools import make_workout_tools


def test_agent_tool_schemas_expose_parameters():
    decls = {FunctionTool(t)._get_declaration().name: FunctionTool(t)._get_declaration()
             for t in make_workout_tools(Path("."))}
    assert set(decls) == {"list_workout_files", "summarize_workouts", "weekly_trends"}
    assert decls["summarize_workouts"].parameters_json_schema["required"] == ["file_name"]


def test_header_mapper_output_parsing():
    out = parse_mapper_output(
        '```json\n{"matches": [{"field": "distance_km", "column": "Strecke", "unit": "km"},'
        ' {"field": "date", "column": "Datum"}], "date_order": "unknown"}\n```'
    )
    assert out == {"columns": {"distance_km": "Strecke", "date": "Datum"},
                   "units": {"distance_km": "km"}, "date_order": None}
    with pytest.raises(ValidationError):  # field must be a template field
        parse_mapper_output('{"matches": [{"field": "speed", "column": "x"}]}')
