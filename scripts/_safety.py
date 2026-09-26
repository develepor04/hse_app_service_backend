"""Shared guard for scripts that truncate/delete real tables (U-016).

Before this, running any of the reset_*.py scripts against the wrong
database — the wrong terminal tab, a mistyped DB_NAME, a shell history
mistake — was unrecoverable data loss with no prompt in between. This adds
one: either the operator types the exact database name back, or the caller
opts in non-interactively via ALLOW_DESTRUCTIVE_RESET=1 (CI fixtures, a
scripted test-data reset pipeline — anywhere a human is not sitting at the
prompt to type a confirmation).
"""
import os
import sys


def confirm_destructive(db_name: str, action: str) -> None:
    if os.environ.get("ALLOW_DESTRUCTIVE_RESET") == "1":
        print(f"ALLOW_DESTRUCTIVE_RESET=1 set — skipping interactive confirmation for: {action}")
        return

    if not sys.stdin.isatty():
        raise SystemExit(
            f"Refusing to {action} on database '{db_name}': no interactive terminal to "
            "confirm from. Set ALLOW_DESTRUCTIVE_RESET=1 if this is intentional automation."
        )

    print(f"\nThis will {action} on database '{db_name}'. This cannot be undone.")
    typed = input(f"Type the database name ('{db_name}') to continue: ").strip()
    if typed != db_name:
        raise SystemExit("Confirmation did not match — aborted, nothing was changed.")
