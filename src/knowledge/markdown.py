"""One markdown document of the register: front matter plus fixed sections.

Every file in `knowledge/` has the same shape, the one the client documents
already use (Step 4 §0, the design consequence of Q1 + Q2): a short front-matter
block of machine fields, one line each, and then plain prose under fixed `##`
headings.

The front matter is read line by line rather than through a YAML parser, for
three reasons a hand-edited file makes concrete:

- **a duplicate key is an error, not a last-value-wins.** "Two statuses in one
  record" is the mistake §8 exists to catch, and a parser that silently keeps the
  second one would hide it;
- **a date stays the text the keeper wrote.** `review_by: 2026-12-21` is compared
  and reported exactly as written, and a typo is reported as a bad date rather
  than arriving as some other type;
- **the error names the line.** A person editing by hand needs to be told which
  line, not which YAML node.

Nothing here knows what any field means. Which fields are required, which values
are allowed, and what the sections must contain are `records.py` and
`validator.py`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Optional

_FENCE: Final[str] = "---"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

#: `key: value`, one field per line. A key is a plain lower-case identifier: the
#: front matter is a machine block, and anything else in it is a mistake.
_FIELD = re.compile(r"^(?P<key>[a-z][a-z0-9_]*)\s*:\s*(?P<value>.*)$")


class DocumentError(ValueError):
    """A register file cannot be read as a document at all."""


@dataclass(frozen=True, slots=True)
class Document:
    """A parsed register file, with nothing interpreted."""

    path: str
    #: Front-matter fields in document order, values exactly as written.
    fields: tuple[tuple[str, str], ...]
    #: The one `#` title. Empty when the file has none.
    title: str
    #: Prose between the title and the first `##` section. A person writing a
    #: file by hand puts a note there, and keeping it means the file survives
    #: a round trip instead of being refused for it.
    preamble: str
    #: Each `##` section and its body, in document order.
    sections: tuple[tuple[str, str], ...]
    #: SHA-256 over the whole file as it is on disk.
    digest: str
    #: The file as it is on disk. Kept because the credential scan (§8 rule 10)
    #: reads the whole file, front matter and prose alike, not the parts a record
    #: is made of.
    text: str

    def field(self, name: str) -> Optional[str]:
        """The field's value, or ``None`` when it is absent.

        An empty value is not absent: `supersedes:` with nothing after it is a
        field the keeper wrote deliberately, and returning `""` lets the caller
        say so.
        """

        for key, value in self.fields:
            if key == name:
                return value
        return None

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.fields)

    def section(self, heading: str) -> Optional[str]:
        """The body under this `##` heading, or ``None`` when it is absent."""

        for name, body in self.sections:
            if name == heading:
                return body
        return None

    @property
    def section_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.sections)

    def version_surface(self) -> str:
        """What a `version` bump has to cover (§2.2).

        `version` goes up on every change to anything below the front matter, or
        to `status`, `tier` or `confidence`. Those three are therefore part of
        the surface; the rest of the front matter is not — bumping `version`
        itself, or writing the `supersedes` line that records the bump, must not
        count as the change that required it.
        """

        graded = "\n".join(
            f"{name}: {self.field(name) or ''}"
            for name in ("status", "tier", "confidence")
        )
        body = "\n".join(f"## {name}\n{text}" for name, text in self.sections)
        return f"{graded}\n# {self.title}\n{self.preamble}\n{body}"

    def version_surface_digest(self) -> str:
        return _sha256(self.version_surface())


def parse_document(text: str, path: str) -> Document:
    """Parse one register file. Raises :class:`DocumentError`."""

    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise DocumentError(
            f"{path}: a register file starts with a `---` front-matter block"
        )
    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == _FENCE
        )
    except StopIteration:
        raise DocumentError(
            f"{path}: the front-matter block is never closed by a second `---`"
        ) from None

    fields: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip():
            continue
        match = _FIELD.match(line)
        if not match:
            raise DocumentError(
                f"{path}:{number}: front matter is one `key: value` per line; "
                f"got {line.strip()[:60]!r}"
            )
        key = match.group("key")
        if key in seen:
            raise DocumentError(
                f"{path}:{number}: `{key}` is set twice; a record has exactly "
                "one of each field"
            )
        seen.add(key)
        fields.append((key, match.group("value").strip()))

    title = ""
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for number, line in enumerate(lines[end + 1 :], start=end + 2):
        heading = _HEADING.match(line)
        if heading is not None and len(heading.group(1)) == 1:
            if title:
                raise DocumentError(
                    f"{path}:{number}: a second `#` title; a record has one"
                )
            if sections:
                raise DocumentError(
                    f"{path}:{number}: the `#` title comes before the first "
                    "`##` section"
                )
            title = heading.group(2).strip()
            continue
        if heading is not None and len(heading.group(1)) == 2:
            name = heading.group(2).strip()
            if any(existing == name for existing, _ in sections):
                raise DocumentError(
                    f"{path}:{number}: `## {name}` appears twice; a reader "
                    "cannot tell which one is the record"
                )
            sections.append((name, []))
            continue
        (sections[-1][1] if sections else preamble).append(line)

    return Document(
        path=path,
        fields=tuple(fields),
        title=title,
        preamble="\n".join(preamble).strip(),
        sections=tuple((name, "\n".join(body).strip()) for name, body in sections),
        digest=_sha256(text),
        text=text,
    )


def parse_table(
    body: str, *, path: str, section: str, columns: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    """The rows of the one pipe table in a section. Raises :class:`DocumentError`.

    The header has to be exactly the columns asked for, in that order. A route
    table with its columns renamed or reordered is not a route table a reader can
    compare with Step 2, and silently reading it by position would compare the
    wrong cells.
    """

    rows: list[tuple[str, ...]] = []
    header: Optional[tuple[str, ...]] = None
    for number, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in stripped.strip("|").split("|"))
        if header is None:
            header = cells
            if tuple(cell.lower() for cell in cells) != tuple(
                column.lower() for column in columns
            ):
                raise DocumentError(
                    f"{path}: the `## {section}` table's columns must be "
                    f"{' | '.join(columns)}; got {' | '.join(cells)}"
                )
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if len(cells) != len(columns):
            raise DocumentError(
                f"{path}: row {number} of the `## {section}` table has "
                f"{len(cells)} cell(s), not {len(columns)}: {stripped[:70]!r}"
            )
        rows.append(cells)

    if header is None:
        raise DocumentError(f"{path}: `## {section}` has no table")
    if not rows:
        raise DocumentError(f"{path}: the `## {section}` table has no rows")
    return tuple(rows)


def load_document(path: Path) -> Document:
    """Read and parse one register file. Raises :class:`DocumentError`."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentError(f"{path}: cannot be read ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise DocumentError(f"{path}: is not UTF-8 text ({exc})") from exc
    return parse_document(text, str(path))


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
