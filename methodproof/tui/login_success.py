"""Rich success panel shown after mp login / mp login --add."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from methodproof.tui.theme import BORDER, DIM, GOLD, GREEN, TEXT

_CONSOLE = Console()


def run(display_name: str, email: str, account_count: int, added: bool) -> None:
    """Render post-login success panel. Always shown regardless of ui_mode."""
    body = Text()
    body.append("✓  ", style=f"bold {GREEN}")

    if added:
        body.append("You have successfully added ", style=TEXT)
        body.append(display_name, style=f"bold {TEXT}")
        body.append(" authentication to your CLI.", style=TEXT)
    else:
        body.append("Signed in as ", style=TEXT)
        body.append(display_name, style=f"bold {TEXT}")
        body.append(".", style=TEXT)

    if email and email != display_name:
        body.append(f"\n   {email}", style=DIM)

    n = account_count
    body.append(
        f"\n\n   {n} account{'s' if n != 1 else ''} on this device  ·  ",
        style=DIM,
    )
    body.append("mp switch", style=f"bold {GOLD}")
    body.append(" to swap", style=DIM)

    title = f"[{GOLD}]  {'Added to CLI' if added else 'Logged In'}  [/{GOLD}]"
    _CONSOLE.print()
    _CONSOLE.print(Panel(body, title=title, border_style=BORDER, padding=(0, 1)))
    _CONSOLE.print()
