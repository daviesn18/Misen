"""Reading a cookbook PDF that has been converted to markdown.

The conversion is lossy in ways that matter, and pretending otherwise is how
a recipe library fills up with plausible nonsense. What actually arrives:

- **Recipe titles are plain text**, not headings. The reliable anchor is the
  line after them: `###### **Per Serving: makes 10**`.
- **Ingredient columns are flattened** into one run-together line each. That is
  `ingredients.py`'s problem and it is the hard one.
- **Whole pages are photographs.** Their text survives only as OCR inside
  `<!-- Start of picture text -->` blocks, sometimes readable, sometimes
  `SS<br>i (a SF Sa. sysi`. Some recipes exist *only* there.
- **Some pages are simply absent.** The table of contents lists them; the
  document doesn't contain them at any quality.

So this module reports three outcomes per recipe in the contents — parsed,
partial, missing — and never invents the difference. A recipe that came out of
OCR is marked as such and carries the warning into Mealie, because the person
reading "1790g pork loin" off their phone at 6pm deserves to know it was read
off a photograph.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from recipes.ingredients import split_lines
from recipes.model import Nutrition, Recipe

# `###### **Per Serving: makes 10**`, with the count sometimes missing.
SERVINGS = re.compile(r"Per Serving:\s*makes\s*(\d+)", re.I)
# `540 Calories` / `46G Protein 62G Carbs 13G Fat`, in any order, any case.
CALORIES = re.compile(r"(\d{2,4})\s*Calories", re.I)
MACROS = re.compile(r"(\d{1,3})\s*g\s*(Protein|Carbs|Fat)", re.I)

HEADING = re.compile(r"^#+\s*(.*?)\s*$")
BOLD_HEADING = re.compile(r"^#+\s*\*\*(.+?)\*\*\s*$")
SECTION_HEADING = re.compile(r"^#+\s*\*\*(.+?):\*\*\s*$")
FOOTER = re.compile(r"^>\s*back to table of contents\s*(\d+)?\s*$", re.I)
STEP = re.compile(r"^-?\s*(\d{1,2})\s*[.)]\s*(.*)$")
# A section heading that got glued to the end of the previous column's last
# line — "2 onions Spanish Rice:". Capitalised words, then a colon, then EOL.
TRAILING_SECTION = re.compile(r"\s((?:[A-Z][\w'&.]*)(?:[ &]+[\w'&.()]+){0,4}\s*:)\s*$")
PICTURE = re.compile(
    r"<!-- Start of picture text -->(.*?)<!-- End of picture text -->", re.S
)


@dataclass
class TocEntry:
    title: str
    page: int
    section: str  # "MEALS" or "PROTEINS"


@dataclass
class ParseResult:
    recipes: list[Recipe] = field(default_factory=list)
    # Titles in the contents that no page could be found for, at any quality.
    missing: list[TocEntry] = field(default_factory=list)

    @property
    def complete(self) -> list[Recipe]:
        return [r for r in self.recipes if r.is_complete()]

    @property
    def partial(self) -> list[Recipe]:
        return [r for r in self.recipes if not r.is_complete()]


def _clean(text: str) -> str:
    """Strip heading markers and markdown emphasis, keeping the words.

    The heading marker has to go: every structural marker in this document
    (`###### **ingredients**`) is a heading, and comparing against the text
    without removing the hashes silently matches nothing.
    """
    text = re.sub(r"^\s*#+\s*", "", text)
    text = re.sub(r"<u>|</u>|~~", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_toc(source: str) -> list[TocEntry]:
    """The contents, which is the only complete list of what should exist.

    Rows sometimes pack two recipes into one cell with `<br>`, matching the
    printed page. Both halves are real recipes.
    """
    entries: list[TocEntry] = []
    section = "MEALS"
    body = source.split("\n# MEALS")[0]

    for line in body.split("\n"):
        heading = BOLD_HEADING.match(line.strip())
        if heading and heading.group(1).strip().upper().startswith("PROTEIN"):
            section = "PROTEINS"
            continue
        row = re.match(r"^\|([^|]+)\|([^|]+)\|\s*$", line.strip())
        if not row or "---" in row.group(1):
            continue
        # Drop the stray "." placeholder cells the conversion leaves behind.
        # Zipping them against the page numbers would shift every title in the
        # row onto the wrong page, or drop the last one entirely.
        titles = [t for t in (_clean(t).strip(" .") for t in row.group(1).split("<br>")) if t]
        pages = [p for p in (_clean(p).strip(" .") for p in row.group(2).split("<br>")) if p]
        for title, page in zip(titles, pages, strict=False):
            if title and page.isdigit():
                entries.append(TocEntry(title=title, page=int(page), section=section))
    return entries


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _find_pages(source: str) -> list[tuple[int | None, str]]:
    """Cut the body into pages on the `back to table of contents N` footer.

    A third of the pages have no footer — it was inside an image. Those pages
    end up appended to the previous chunk, which is why chunks are split again
    on the servings line below rather than trusted as one recipe each.
    """
    body = source[source.index("\n# MEALS") :]
    chunks: list[tuple[int | None, str]] = []
    current: list[str] = []
    for line in body.split("\n"):
        footer = FOOTER.match(line.strip())
        if footer:
            page = int(footer.group(1)) if footer.group(1) else None
            chunks.append((page, "\n".join(current)))
            current = []
        else:
            current.append(line)
    if any(line.strip() for line in current):
        chunks.append((None, "\n".join(current)))
    return chunks


def _split_on_recipes(chunk: str) -> list[list[str]]:
    """One chunk may hold several recipes. The servings line starts each one.

    The title is the last non-empty line *before* that anchor, so each block
    reaches back one line further than the anchor itself.
    """
    lines = chunk.split("\n")
    anchors = [i for i, line in enumerate(lines) if SERVINGS.search(line)]
    if not anchors:
        return []

    blocks: list[list[str]] = []
    for position, anchor in enumerate(anchors):
        start = anchor
        # Walk back to the title line.
        cursor = anchor - 1
        while cursor >= 0 and not lines[cursor].strip():
            cursor -= 1
        if cursor >= 0:
            start = cursor
        end = anchors[position + 1] - 1 if position + 1 < len(anchors) else len(lines)
        # Don't reach past the next recipe's title line.
        while end > start and not lines[end - 1].strip():
            end -= 1
        blocks.append(lines[start:end])
    return blocks


def _macros(text: str) -> Nutrition:
    nutrition = Nutrition()
    calories = CALORIES.search(text)
    if calories:
        nutrition.calories = int(calories.group(1))
    for amount, kind in MACROS.findall(text):
        kind = kind.lower()
        if kind == "protein":
            nutrition.protein_g = int(amount)
        elif kind == "carbs":
            nutrition.carbs_g = int(amount)
        elif kind == "fat":
            nutrition.fat_g = int(amount)
    return nutrition


def _picture_text(block: str) -> str:
    """OCR content, with the pure-noise blocks thrown away.

    A block of real text has words in it. A block of `SS<br>i (a SF Sa. sysi`
    does not, and letting it through would put garbage in a recipe.
    """
    recovered = []
    for match in PICTURE.findall(block):
        text = match.replace("<br>", "\n")
        words = re.findall(r"\b[a-z]{3,}\b", text.lower())
        # Real recipe OCR is mostly words. Noise is mostly punctuation and
        # one- or two-character fragments.
        letters = sum(len(w) for w in words)
        if len(words) >= 12 and letters > len(text) * 0.35:
            recovered.append(text)
    return "\n".join(recovered)


def _is_junk_title(title: str) -> bool:
    """Is this "title" actually a scrap of an image block?

    On about a sixth of the pages the recipe name is part of the photograph,
    so the line above the servings anchor is whatever OCR debris came next —
    `480 Calories<br><!-- End of picture text -->`. The recipe underneath is
    perfectly good; only its name is missing, and the page number recovers it.
    """
    if not title:
        return True
    if "<!--" in title or "<br>" in title:
        return True
    if CALORIES.search(title) or MACROS.search(title):
        return True
    return not re.search(r"[A-Za-z]{3}", title)


def _parse_block(lines: list[str], page: int | None) -> Recipe | None:
    title = _clean(lines[0])
    if SERVINGS.search(lines[0]):
        return None
    if _is_junk_title(title):
        title = ""  # resolved from the page number against the contents

    recipe = Recipe(title=title, page=page)
    joined = "\n".join(lines)

    servings = SERVINGS.search(joined)
    if servings:
        recipe.servings = int(servings.group(1))

    from_picture = _picture_text(joined)
    # Strip the picture blocks out of the prose so OCR text isn't parsed twice.
    prose = PICTURE.sub("\n", joined)

    recipe.nutrition = _macros(prose)
    if recipe.nutrition.is_empty() and from_picture:
        recipe.nutrition = _macros(from_picture)

    ingredients, sections, instructions, unsure = _read_body(prose)

    if not ingredients and from_picture:
        ingredients, sections, _, unsure = _read_body(from_picture, ocr=True)
        if ingredients:
            recipe.warnings.append(
                "Ingredients were read from a photo of the page and may contain "
                "OCR errors — check them before shopping."
            )
    if not instructions:
        instructions = _read_steps(from_picture)
        if instructions:
            recipe.warnings.append("Steps were read from a photo of the page.")

    if unsure:
        # Named, not counted. "Check these three lines" is actionable; "3
        # ingredients may be wrong" sends someone hunting through twenty.
        recipe.warnings.append(
            "These lines may still hold two ingredients run together: "
            + "; ".join(f"\u201c{line}\u201d" for line in unsure)
        )

    recipe.ingredients = ingredients
    recipe.sections = sections
    recipe.instructions = instructions
    return recipe


def _is_step_continuation(line: str) -> bool:
    """A wrapped fragment of the step above, not a new ingredient.

    Ingredient lines start with a quantity or a capitalised food. A wrap starts
    with the bullet the converter inserted, or mid-sentence in lower case.
    """
    text = _clean(line)
    if not text:
        return False
    if line.lstrip().startswith(("- ", "-\t", "*")) and not re.match(r"^-?\s*\d", text):
        return True
    return text[:1].islower()


def _read_steps(text: str) -> list[str]:
    steps: dict[int, str] = {}
    for line in text.split("\n"):
        match = STEP.match(_clean(line))
        if match and match.group(2).strip():
            number = int(match.group(1))
            # Later, longer text for the same number wins: the prose copy of a
            # step is usually complete where the OCR copy is truncated.
            if len(match.group(2)) > len(steps.get(number, "")):
                steps[number] = match.group(2).strip()
    return [steps[n] for n in sorted(steps)]


def _read_body(
    text: str, ocr: bool = False
) -> tuple[list[str], dict[int, str], list[str], list[str]]:
    """Pull ingredients (with their section headings) and steps out of a block.

    The document alternates `ingredients` and `instructions` markers, and not
    always in that order — several pages print the instructions header first
    and the ingredients underneath it. So the markers switch a mode rather than
    defining a region, and steps are collected by their numbering wherever they
    appear.
    """
    ingredient_lines: list[str] = []
    sections: dict[int, str] = {}
    pending_section: str | None = None
    mode: str | None = None
    step_source: list[str] = []
    in_step = False

    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue

        stripped = _clean(line).lower()
        if stripped == "ingredients":
            mode = "ingredients"
            continue
        if stripped == "instructions":
            mode = "instructions"
            continue

        if STEP.match(_clean(line)):
            step_source.append(line)
            in_step = True
            continue

        # A step whose text wrapped onto the next line, which the conversion
        # renders as a stray bullet: "- **two lemons, ...** . Stir to combine".
        # Without this it lands in the ingredient list as a sentence, and the
        # step it belongs to stays truncated mid-phrase. One fix, both bugs.
        if in_step and _is_step_continuation(line):
            step_source[-1] = step_source[-1].rstrip() + " " + _clean(line).lstrip("- ")
            continue
        in_step = False

        section = SECTION_HEADING.match(line)
        if section and not ocr:
            pending_section = _clean(section.group(1))
            continue
        # Some headings lose their markdown even outside the image blocks, so
        # a bare "Corn Starch Slurry (if needed):" arrives looking like an
        # ingredient. A short, digit-free line ending in a colon is a heading.
        # Tested on the *cleaned* text: "**Spanish Rice:**" does not end in a
        # colon until the emphasis markers come off.
        bare = _clean(line)
        if bare.endswith(":") and len(bare) < 45 and not re.search(r"\d", bare):
            pending_section = bare.rstrip(":")
            continue

        if HEADING.match(line) and line.startswith("#"):
            continue  # nutrition lines and other headings
        if SERVINGS.search(line) or CALORIES.search(line):
            continue

        if mode == "ingredients":
            cleaned = _clean(line)
            if not cleaned:
                continue
            # A column heading that landed at the end of the previous column's
            # last line: "2 onions Spanish Rice:". It belongs to the ingredients
            # that follow, not to the onions.
            trailing = TRAILING_SECTION.search(cleaned)
            carried: str | None = None
            prefix = cleaned[: trailing.start()].strip() if trailing else ""
            # Only carry when what's left really is an ingredient. Without the
            # digit test, a heading that is simply two words — "Spanish Rice:"
            # — gets cut in half, leaving "Spanish" in the shopping list.
            if trailing and re.search(r"\d", prefix):
                carried = trailing.group(1).strip().rstrip(":")
                cleaned = prefix

            if pending_section is not None:
                sections[len(ingredient_lines)] = pending_section
                pending_section = None
            ingredient_lines.append(cleaned)
            if carried:
                pending_section = carried

    split = split_lines(ingredient_lines)

    # Section indices were recorded against raw lines; remap them onto the
    # split ingredients so a heading still lands on its first ingredient.
    remapped: dict[int, str] = {}
    offset = 0
    for index, line in enumerate(ingredient_lines):
        if index in sections:
            remapped[offset] = sections[index]
        offset += len(split_lines([line]).ingredients)

    return (
        split.ingredients,
        remapped,
        _read_steps("\n".join(step_source)),
        split.suspicious,
    )


def parse_cookbook(
    source: str, *, author: str = "", origin: str = "", tags: list[str] | None = None
) -> ParseResult:
    """Parse a converted cookbook. Reports what it couldn't find."""
    toc = parse_toc(source)
    result = ParseResult()

    for page, chunk in _find_pages(source):
        for block in _split_on_recipes(chunk):
            recipe = _parse_block(block, page)
            if recipe is None:
                continue
            recipe.author = author
            recipe.source = origin
            recipe.tags = list(tags or [])
            result.recipes.append(recipe)

    by_title = {_normalise(e.title): e for e in toc}
    by_page = {e.page: e for e in toc}

    for recipe in result.recipes:
        entry = by_title.get(_normalise(recipe.title))
        if entry is None and recipe.page is not None:
            # A recipe whose name was inside the photograph. The page footer
            # survived, and the contents knows what is printed on that page.
            entry = by_page.get(recipe.page)
            if entry and not recipe.title:
                recipe.title = entry.title
                recipe.warnings.append("Title recovered from the table of contents.")
        if entry:
            # The contents carries the printed capitalisation; the body
            # sometimes shouts it and sometimes whispers it.
            recipe.title = entry.title
            recipe.page = recipe.page or entry.page
            if entry.section == "PROTEINS" and "protein-only" not in recipe.tags:
                recipe.tags.append("protein-only")

    # Anything in the contents with no page parsed at any quality is reported,
    # never quietly dropped.
    found = {_normalise(r.title) for r in result.recipes if r.title}
    result.missing = [e for e in toc if _normalise(e.title) not in found]
    result.recipes = [r for r in result.recipes if r.title]
    return result
