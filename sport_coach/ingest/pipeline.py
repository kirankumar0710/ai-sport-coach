"""import_file: read -> map -> convert -> save, plus the result shown to the user."""

from dataclasses import dataclass
from pathlib import Path

from sport_coach import workouts
from sport_coach.ingest.convert import Conversion, convert
from sport_coach.ingest.mapping import HeaderMapper, Mapping, build_mapping
from sport_coach.ingest.parsers import blank
from sport_coach.ingest.reader import read_table
from sport_coach.schema import FIELDS as TEMPLATE_FIELDS, MEASURES
from sport_coach.workouts import WorkoutDataError


@dataclass
class ImportResult:
    name: str                      # stored file name
    count: int
    matched_template: bool         # False -> the user is told we mapped it
    mapping: Mapping
    conversion: Conversion
    csv_text: str                  # what was saved (offered as a download)

    def messages(self) -> list[str]:
        out = self.mapping.describe()
        for f in self.conversion.derived:
            out.append(f"{TEMPLATE_FIELDS[f].label} — calculated")
        missing = [TEMPLATE_FIELDS[f].label for f in MEASURES
                   if f not in self.mapping.columns and f not in self.conversion.derived]
        if missing:
            out.append("Not in your file: " + ", ".join(missing))
        return out


def import_file(
    data_dir: Path,
    file_name: str,
    content: bytes,
    mapper: HeaderMapper | None = None,
    cache_path: Path | None = None,
) -> ImportResult:
    """Read any workout file, map it onto the template, convert and save it."""
    table = read_table(file_name, content)
    if not any(any(not blank(v) for v in r) for r in table.rows):
        raise WorkoutDataError("The file has a header but no data rows")
    mapping = build_mapping(table, mapper, cache_path)
    conv = convert(table, mapping)
    if not conv.rows:
        reasons = "; ".join(f"row {ln}: {why}" for ln, why in conv.skipped[:3])
        raise WorkoutDataError(f"No usable workouts found ({reasons})")
    text = workouts.to_csv(conv.rows)
    name, count = workouts.save_csv(data_dir, file_name, text)
    return ImportResult(name, count, mapping.source == "template", mapping, conv, text)
