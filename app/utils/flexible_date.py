"""Parse dates from Excel/CSV uploads that don't come in ISO format.

Uploaded org/master-data sheets carry dates written by hand in whatever
format the source spreadsheet used (e.g. "15-Mar-2015"), not the ISO
"YYYY-MM-DD" that `date.fromisoformat` and `<input type="date">` require.
A silent `except: pass` around a strict ISO parse was dropping these dates
entirely — this gives every caller one place to parse them properly.
"""
from datetime import date, datetime
from typing import Optional

_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%d-%b-%Y",       # 15-Mar-2015
    "%d-%B-%Y",       # 15-March-2015
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%B %d, %Y",      # March 15, 2015
    "%d %B %Y",       # 15 March 2015
    "%b %d, %Y",      # Mar 15, 2015
)


def parse_flexible_date(value) -> Optional[str]:
    """Best-effort parse of a spreadsheet date cell into an ISO 'YYYY-MM-DD' string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    s = str(value).strip()
    if not s:
        return None

    for fmt in _FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None
