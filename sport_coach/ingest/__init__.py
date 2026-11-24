"""Import any workout file into the app template (sport_coach.schema).

Users export workouts from many apps and spreadsheets, each with its own
headers, units and date formats. No review step - we map automatically:

  1. read the table (CSV/TSV/TXT with any delimiter, or any Excel/ODS sheet)
     and find the header row (title rows above it are ignored)
  2. if the headers already are our template columns, use them as-is
  3. otherwise map user headers -> template fields:
       - an LLM mapper (headers + a few sample rows -> JSON), when available
       - built-in rules (synonyms, close spelling) as fallback and gap-filler
     every proposed match is checked against the column's actual values
  4. copy the data into the template in Python: convert units, parse dates,
     derive pace/duration/distance where possible
  5. save canonical CSV; rows without a date or any measurement are skipped
     and reported

The LLM only names columns and units. All values are converted here, in
deterministic code, so a model can never invent or alter a number.

Modules (dependencies flow downwards):
  parsers   cell values: numbers, durations, dates; does a column fit a field
  rules     built-in header matching (fallback / gap-filler for the AI)
  reader    file -> Table, header-row detection
  mapping   template / AI / rules -> Mapping (columns + units)
  convert   Table + Mapping -> template rows
  pipeline  import_file and ImportResult
"""

from sport_coach.ingest.convert import Conversion, convert
from sport_coach.ingest.mapping import UNIT_FACTORS, HeaderMapper, Mapping, build_mapping, is_template
from sport_coach.ingest.parsers import DATE_ORDERS, content_fit, parse_clock, parse_date, parse_number
from sport_coach.ingest.pipeline import ImportResult, import_file
from sport_coach.ingest.reader import SAMPLE_ROWS, UPLOAD_TYPES, Table, read_table
from sport_coach.ingest.rules import RULES, rule_mapping

__all__ = [
    "Conversion", "DATE_ORDERS", "HeaderMapper", "ImportResult", "Mapping", "RULES", "SAMPLE_ROWS",
    "Table", "UNIT_FACTORS", "UPLOAD_TYPES", "build_mapping", "content_fit", "convert", "import_file",
    "is_template", "parse_clock", "parse_date", "parse_number", "read_table", "rule_mapping",
]
