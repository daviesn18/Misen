"""`python -m recipes` — parse a cookbook, review it, then import it.

Three subcommands, in the order you should use them:

    parse   markdown → JSON, and a report of what didn't survive
    review  the parsed JSON as readable markdown, for a human to check
    import  JSON → Mealie

Parsing and importing are separate on purpose. The conversion from PDF loses
things, and the review step is where a person catches that before ninety
recipes with a wrong ingredient are sitting in the library. `import` reads the
reviewed JSON, so corrections made by hand survive.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from recipes.cookbook import parse_cookbook
from recipes.mealie import MealieUploader, import_recipes
from recipes.model import Nutrition, Recipe


def _to_json(recipe: Recipe) -> dict:
    data = asdict(recipe)
    # Section keys are ints; JSON object keys are strings.
    data["sections"] = {str(k): v for k, v in recipe.sections.items()}
    return data


def _from_json(data: dict) -> Recipe:
    nutrition = Nutrition(**data.pop("nutrition", {}) or {})
    sections = {int(k): v for k, v in (data.pop("sections", {}) or {}).items()}
    return Recipe(nutrition=nutrition, sections=sections, **data)


def load(path: Path) -> list[Recipe]:
    payload = json.loads(path.read_text())
    return [_from_json(entry) for entry in payload["recipes"]]


def cmd_parse(args: argparse.Namespace) -> int:
    source = Path(args.source).read_text()
    result = parse_cookbook(
        source,
        author=args.author,
        origin=args.origin,
        tags=args.tag or [],
    )

    payload = {
        "source": Path(args.source).name,
        "author": args.author,
        "origin": args.origin,
        "recipes": [_to_json(r) for r in result.recipes],
        "missing": [{"title": m.title, "page": m.page} for m in result.missing],
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    tally = Counter(r.confidence for r in result.recipes)
    print(f"parsed       {len(result.recipes)} recipes, "
          f"{sum(len(r.ingredients) for r in result.recipes)} ingredients")
    print(f"  clean      {tally['clean']}  — parsed off text, nothing flagged")
    print(f"  check      {tally['check']}  — a line or two to look over")
    print(f"  poor       {tally['poor']}  — the page came back as fragments; retype these")
    print(f"missing      {len(result.missing)} listed in the contents but not in the file")
    print(f"written to   {args.out}")
    if result.missing:
        print("\nNot recoverable from this file — these pages are photographs:")
        for entry in result.missing:
            print(f"  p{entry.page:<4} {entry.title}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.parsed).read_text())
    recipes = [_from_json(entry) for entry in payload["recipes"]]

    lines = [
        f"# {payload.get('origin') or 'Cookbook'} — import review",
        "",
        f"{len(recipes)} recipes parsed from `{payload.get('source')}`.",
        "",
        "This file is a view. The data is the JSON next to it — fix anything "
        "wrong there, then run `import`, and the corrections survive.",
        "",
    ]

    poor = [r for r in recipes if r.confidence == "poor"]
    check = [r for r in recipes if r.confidence == "check"]

    if poor:
        lines += [
            "## Retype these",
            "",
            "Their pages were photographs printed in two columns, and the text "
            "came back interleaved — ingredients are cut across each other and "
            "cannot be put back in order automatically. Faster to type from the "
            "book than to repair.",
            "",
        ]
        for recipe in poor:
            lines.append(
                f"- [{recipe.title}](#{recipe.slug}) — p{recipe.page}, "
                f"{recipe.orphan_rate:.0%} of lines are fragments"
            )
        lines.append("")

    if check:
        lines += ["## Worth a look", ""]
        for recipe in check:
            lines.append(f"- [{recipe.title}](#{recipe.slug}) — p{recipe.page}")
        lines.append("")

    if payload.get("missing"):
        lines += [
            "## Not in the file",
            "",
            "Listed in the cookbook's contents, but their pages are photographs "
            "with no recoverable text. They need typing in by hand.",
            "",
        ]
        for entry in payload["missing"]:
            lines.append(f"- p{entry['page']} — {entry['title']}")
        lines.append("")

    lines += ["## Recipes", ""]
    for recipe in recipes:
        lines.append(f'<a id="{recipe.slug}"></a>')
        lines.append(f"### {recipe.title}")
        meta = []
        if recipe.servings:
            meta.append(f"serves {recipe.servings}")
        if recipe.page:
            meta.append(f"p{recipe.page}")
        if not recipe.nutrition.is_empty():
            macros = recipe.nutrition
            meta.append(
                f"{macros.calories} cal · {macros.protein_g}g protein · "
                f"{macros.carbs_g}g carbs · {macros.fat_g}g fat"
            )
        if meta:
            lines += ["", " — ".join(meta)]
        if recipe.confidence == "poor":
            lines += ["", "> **Retype this one.** The page came back as fragments."]
        for warning in recipe.warnings:
            lines += ["", f"> **Check.** {warning}"]

        lines += ["", "**Ingredients**", ""]
        for index, ingredient in enumerate(recipe.ingredients):
            if index in recipe.sections:
                lines.append(f"- *{recipe.sections[index]}*")
            lines.append(f"  - {ingredient}")
        lines += ["", "**Method**", ""]
        for number, step in enumerate(recipe.instructions, start=1):
            lines.append(f"{number}. {step}")
        lines.append("")

    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out} — {len(recipes)} recipes, "
          f"{len(check)} to check, {len(poor)} to retype")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    recipes = load(Path(args.parsed))
    allowed = {"clean", "check", "poor"}
    if args.min_confidence == "check":
        allowed = {"clean", "check"}
    elif args.min_confidence == "clean":
        allowed = {"clean"}
    skipped = [r for r in recipes if r.confidence not in allowed]
    recipes = [r for r in recipes if r.confidence in allowed]
    if skipped:
        print(f"holding back {len(skipped)} recipes below --min-confidence")

    token = args.token or os.environ.get("MEALIE_API_TOKEN", "")
    if not token:
        print("No token. Pass --token or set MEALIE_API_TOKEN.", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"would import {len(recipes)} recipes to {args.url}")
        for recipe in recipes[:10]:
            print(f"  {recipe.slug}  ({len(recipe.ingredients)} ingredients)")
        if len(recipes) > 10:
            print(f"  … and {len(recipes) - 10} more")
        return 0

    with MealieUploader(args.url, token) as uploader:
        report = import_recipes(uploader, recipes, skip_existing=not args.force)

    print(report.summary())
    for title, error in report.failed:
        print(f"  FAILED  {title}: {error}", file=sys.stderr)
    return 1 if report.failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recipes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="cookbook markdown → JSON")
    p.add_argument("source", help="the converted cookbook (.md)")
    p.add_argument("--out", default="recipes.json")
    p.add_argument("--author", default="", help="credited on every recipe")
    p.add_argument("--origin", default="", help="book title, stored as the source")
    p.add_argument("--tag", action="append", help="tag every recipe (repeatable)")
    p.set_defaults(func=cmd_parse)

    r = sub.add_parser("review", help="JSON → readable markdown")
    r.add_argument("parsed", help="the JSON from `parse`")
    r.add_argument("--out", default="review.md")
    r.set_defaults(func=cmd_review)

    i = sub.add_parser("import", help="JSON → Mealie")
    i.add_argument("parsed", help="the JSON from `parse`")
    i.add_argument("--url", required=True, help="https://mealie.misen.<domain>")
    i.add_argument("--token", default="", help="or set MEALIE_API_TOKEN")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument(
        "--min-confidence",
        choices=("clean", "check", "any"),
        default="check",
        help=(
            "lowest parse quality to import. 'check' (the default) leaves out "
            "the recipes whose pages came back as fragments"
        ),
    )
    i.add_argument(
        "--force",
        action="store_true",
        help="import even if a recipe with that slug already exists",
    )
    i.set_defaults(func=cmd_import)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
