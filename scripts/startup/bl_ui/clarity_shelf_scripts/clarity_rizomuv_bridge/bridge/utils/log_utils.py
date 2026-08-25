"""Utility functions for printing to the console."""

from typing import Literal, Optional


class Table:
    """A table formatter for console output."""

    def __init__(
        self,
        title: str,
        columns: list[str],
        padding: int = 1,
        alignment: Literal["left", "center", "right"] = "left",
    ):
        self.columns = columns
        self.title = title
        self.padding = padding
        self.alignment = alignment
        self.rows: list[list[str]] = []
        self._widths: Optional[list[int]] = None

    def add_row(self, row: list[str]) -> None:
        """Add a row to the table."""
        if len(row) != len(self.columns):
            raise ValueError(f"Row has {len(row)} columns, expected {len(self.columns)}")
        self.rows.append([str(cell) for cell in row])
        self._widths = None  # Invalidate cached widths

    def add_rows(self, rows: list[list[str]]) -> None:
        """Add multiple rows to the table."""
        for row in rows:
            self.add_row(row)

    def _calculate_widths(self) -> list[int]:
        """Calculate optimal column widths."""
        if self._widths is None:
            widths = [len(col) for col in self.columns]
            for row in self.rows:
                for i, cell in enumerate(row):
                    widths[i] = max(widths[i], len(cell))
            self._widths = widths
        return self._widths

    def _format_cell(self, content: str, width: int) -> str:
        """Format a cell with proper alignment and padding."""
        if self.alignment == "center":
            content = content.center(width)
        elif self.alignment == "right":
            content = content.rjust(width)
        else:
            content = content.ljust(width)

        return " " * self.padding + content + " " * self.padding

    def _get_separator(self, widths: list[int]) -> str:
        """Generate table separator line."""
        total_width = sum(w + 2 * self.padding for w in widths) + len(widths) - 1
        return "─" * total_width

    def __str__(self) -> str:
        """Return the formatted table as a string."""
        if not self.rows:
            return f"\n{' ' * self.padding}{self.title or 'Empty Table'}\n(no data)"

        widths = self._calculate_widths()
        separator = self._get_separator(widths)
        lines = []

        # Title
        if self.title:
            lines.append(f"\n{' ' * self.padding}{self.title}")

        # Top border
        lines.append(separator)

        # Headers
        header_cells = [self._format_cell(col, widths[i]) for i, col in enumerate(self.columns)]
        lines.append("│".join(header_cells))
        lines.append(separator)

        # Data rows
        for row in self.rows:
            row_cells = [self._format_cell(cell, widths[i]) for i, cell in enumerate(row)]
            lines.append("│".join(row_cells))

        return "\n".join(lines) + "\n"

    def print(self) -> None:
        """Print the table to console."""
        print(self, "\n")
