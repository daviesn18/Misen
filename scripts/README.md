# Getting recipes into Mealie

One-off importers. Each reads some export or document, produces the same
`Recipe` shape, and hands it to the same uploader — so adding a source means
writing a parser, not another end-to-end pipeline.

| Source | Status |
|---|---|
| Cookbook PDF converted to markdown | done — `recipes.cookbook` |
| Recipe Keeper `.zip` | not written — needs the export |

---

## The three steps

```sh
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

# 1. markdown → JSON, with a report of what didn't survive
python -m recipes parse cookbook.md \
    --out ../docs/recipes/my-cookbook.json \
    --author "Author Name" \
    --origin "Book Title" \
    --tag "slow cooker"

# 2. JSON → readable markdown, for a human to check
python -m recipes review ../docs/recipes/my-cookbook.json \
    --out ../docs/recipes/my-cookbook-review.md

# 3. JSON → Mealie
python -m recipes import ../docs/recipes/my-cookbook.json \
    --url https://mealie.misen.<domain> --dry-run
```

`import` reads `MEALIE_API_TOKEN` from the environment, or takes `--token`.

**Parse and import are separate on purpose.** The JSON in the middle is the
thing you correct. Fix a bad ingredient there, run `review` again to see it,
then import — the correction survives, and re-running `parse` is the only
thing that would overwrite it.

**Importing is resumable.** Existing slugs are fetched once and skipped, so a
run that dies at recipe sixty finishes the job on the next attempt instead of
creating sixty duplicates. `--force` overrides that.

---

## What "confidence" means

A cookbook PDF converted to markdown is lossy, and the losses are not evenly
spread. Each recipe comes out as one of three:

| | What it means | What to do |
|---|---|---|
| **clean** | Parsed from real text, nothing flagged | Nothing |
| **check** | Came off a photographed page, or one line looked ambiguous | Read the flagged lines |
| **poor** | The page came back as fragments | Retype it from the book |

`import` defaults to `--min-confidence check`, which leaves the `poor` ones
out. They aren't hidden — `review` lists them first, with the page number.

**Why `poor` exists.** Some pages are photographs of a two-column layout, and
the OCR reads straight across both columns. The tail of each ingredient ends
up three lines from its head:

```
1790g (64oz) flat cut
brisket or chuck eye roast
OR lean steak of choice
```

No line-based parser recovers that, and a "repair" would be a guess about what
someone is going to buy and eat. Naming the recipe and its page number is more
useful than importing something that reads like a recipe and isn't.

---

## The hard part

`ingredients.py`. A two-column ingredient list flattens to one line per column
pair with no separator:

```
900g (32oz) chicken breast 120g red enchilada sauce 2 Tbsp garlic purée
```

Nothing downstream works until those come apart — Mealie parses each *line*
into a food, and Misen's shopping-list diff reads those foods, so one line in
means one shopping item that reads like a paragraph.

The scan splits on a quantity, or on a known unquantified phrase ("Dash of",
"Juice of", "Salt and pepper"). The phrase list was read off a real cookbook,
not imagined, and it holds phrases rather than words on purpose: a bare "Salt"
splits "Salt and pepper" down the middle.

Three cases it deliberately does *not* split, each of which would otherwise
halve a common ingredient:

- `2% cottage cheese`, `1% milk` — a digit welded to a percent sign describes
  the food rather than counting it
- `1/3-fat cream cheese` — likewise a hyphenated descriptor
- `(3 ⅓ cups)` — a number in parentheses belongs to the line already running

And where it is unsure, it leaves the line whole and says so. A wrong split
looks correct and quietly buys the wrong thing; an unsplit line is visibly
wrong to whoever reads the review file.

---

## Adding a source

Write a module that returns `list[Recipe]` (see `model.py`) and add a
subcommand. `to_mealie`, the uploader, the review report, and the confidence
scoring all come for free.

Mealie's field names are not guessable and were read off its v3.22.0 schemas
rather than remembered — `RecipeIngredient` has no `isFood`, `display` has to
be set explicitly or Mealie recomputes it, and `POST /api/recipes` returns a
bare JSON string rather than an object. `tests/test_mealie.py` pins all three,
so a version bump that renames one fails there rather than in a library of
quietly mangled recipes.

---

## Tests

```sh
.venv/bin/python -m pytest tests/ -q
```

Every fixture in `test_cookbook.py` and `test_ingredients.py` reproduces a
shape from a real converted cookbook, including the OCR noise and the stutter
where a photographed page reads the same words three times. Tidy invented
inputs would test a problem nobody has.
