"""The app's workout template: the single definition of our canonical CSV.

Every stored workout file has exactly these columns, in this order. Columns a
user's file could not supply are left empty. The descriptions are also given
to the LLM that maps user headers onto this template.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateField:
    name: str
    label: str
    kind: str                    # date | text | number | duration | pace
    unit: str                    # unit stored in our CSV
    description: str
    source_units: tuple[str, ...] = ()  # units a user's column may be in (converted on import)


TEMPLATE: tuple[TemplateField, ...] = (
    TemplateField("date", "Date", "date", "YYYY-MM-DD",
                  "Day the workout happened (a date or date-time)."),
    TemplateField("activity", "Activity", "text", "",
                  "Type of workout or sport, e.g. run, ride, swim, walk."),
    TemplateField("distance_km", "Distance", "number", "km",
                  "Distance covered.", ("km", "mi", "m")),
    TemplateField("duration_min", "Duration", "duration", "min",
                  "How long the workout took (moving or elapsed time).", ("min", "s", "h", "clock")),
    TemplateField("pace_min_per_km", "Pace", "pace", "min/km",
                  "Average pace, time per distance (e.g. 5:30 per km).", ("min/km", "min/mi")),
    TemplateField("calories", "Calories", "number", "kcal",
                  "Energy burned."),
    TemplateField("avg_hr", "Avg heart rate", "number", "bpm",
                  "Average heart rate."),
    TemplateField("max_hr", "Max heart rate", "number", "bpm",
                  "Maximum heart rate."),
    TemplateField("elevation_gain_m", "Elevation gain", "number", "m",
                  "Total ascent / climb.", ("m", "ft")),
    TemplateField("cadence_spm", "Cadence", "number", "spm",
                  "Average steps (or revolutions) per minute."),
    TemplateField("notes", "Notes", "text", "",
                  "Free text: workout title, session name, comments."),
)

FIELDS: dict[str, TemplateField] = {f.name: f for f in TEMPLATE}
COLUMNS: list[str] = [f.name for f in TEMPLATE]
NUMERIC: list[str] = [f.name for f in TEMPLATE if f.kind in ("number", "duration", "pace")]
MEASURES: list[str] = NUMERIC  # an import needs a date plus at least one of these
