from google.adk.models.lite_llm import LiteLlm

from sport_coach.config import ProviderConfig
from sport_coach.llm.factory import build_generation_config, build_model, supported_providers


def test_supported_providers():
    assert {"gemini", "anthropic", "openai"} <= set(supported_providers())


def test_gemini_is_native_model_string():
    assert build_model(ProviderConfig("gemini", "gemini-2.5-flash", "GEMINI_API_KEY", "k")) == "gemini-2.5-flash"


def test_anthropic_and_openai_use_litellm():
    a = build_model(ProviderConfig("anthropic", "claude-sonnet-5-5", "ANTHROPIC_API_KEY", "k"))
    o = build_model(ProviderConfig("openai", "gpt-4.1", "OPENAI_API_KEY", "k"))
    assert isinstance(a, LiteLlm) and a.model == "anthropic/claude-sonnet-5-5"
    assert isinstance(o, LiteLlm) and o.model == "openai/gpt-4.1"


def test_generation_config():
    gc = build_generation_config(ProviderConfig("gemini", "m", "K", temperature=0.2, max_output_tokens=100))
    assert gc.temperature == 0.2 and gc.max_output_tokens == 100


def test_agent_tool_schemas_expose_parameters():
    from pathlib import Path

    from google.adk.tools.function_tool import FunctionTool

    from sport_coach.tools.workout_tools import make_workout_tools

    decls = {FunctionTool(t)._get_declaration().name: FunctionTool(t)._get_declaration()
             for t in make_workout_tools(Path("."))}
    assert set(decls) == {"list_workout_files", "summarize_workouts", "weekly_trends"}
    schema = decls["summarize_workouts"].parameters_json_schema
    assert schema["required"] == ["file_name"]


def test_header_mapper_output_parsing():
    import pytest
    from pydantic import ValidationError

    from sport_coach.agents.header_mapper import parse_mapper_output

    out = parse_mapper_output(
        '```json\n{"matches": [{"field": "distance_km", "column": "Strecke", "unit": "km"},'
        ' {"field": "date", "column": "Datum"}], "date_order": "unknown"}\n```'
    )
    assert out == {"columns": {"distance_km": "Strecke", "date": "Datum"},
                   "units": {"distance_km": "km"}, "date_order": None}
    with pytest.raises(ValidationError):  # field must be a template field
        parse_mapper_output('{"matches": [{"field": "speed", "column": "x"}]}')
