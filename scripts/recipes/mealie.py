"""Pushing parsed recipes into Mealie.

Two calls per recipe, because that is what Mealie's API is:

    POST /api/recipes          {"name": "..."}   → returns the slug, as a string
    PUT  /api/recipes/{slug}   the whole recipe

Read off Mealie v3.22.0's own routers (`recipe_crud_routes.py`), not from
memory. `CreateRecipe` really does accept nothing but a name, and the create
call really does return a bare JSON string rather than an object.

**Importing is resumable.** A hundred recipes over a home connection will fail
somewhere, and the fix must never be "delete everything and start again".
Existing slugs are fetched once up front and skipped, so re-running finishes
the job instead of duplicating it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from recipes.model import Recipe, to_mealie

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{len(self.created)} created"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} already there")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


class MealieUploader:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def __enter__(self) -> MealieUploader:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def existing_slugs(self) -> set[str]:
        """Every recipe already in the library, so a re-run is a no-op."""
        slugs: set[str] = set()
        page = 1
        while True:
            response = self._client.get(
                "/api/recipes", params={"page": page, "perPage": 100}
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", [])
            slugs.update(item["slug"] for item in items if item.get("slug"))
            if not items or page >= (payload.get("total_pages") or payload.get("totalPages") or 1):
                break
            page += 1
        return slugs

    def create(self, recipe: Recipe) -> str:
        """Create then fill. Returns the slug Mealie assigned.

        Mealie's slug is its own business — it may differ from ours when a name
        collides — so the slug it hands back is the one used for the update,
        never the one computed locally.
        """
        created = self._client.post("/api/recipes", json={"name": recipe.title})
        created.raise_for_status()
        slug = created.json()
        if not isinstance(slug, str):  # pragma: no cover — API contract changed
            raise RuntimeError(f"Mealie returned {slug!r} instead of a slug")

        payload = to_mealie(recipe)
        payload["slug"] = slug
        updated = self._client.put(f"/api/recipes/{slug}", json=payload)
        updated.raise_for_status()
        return slug


def import_recipes(
    uploader: MealieUploader, recipes: list[Recipe], *, skip_existing: bool = True
) -> ImportReport:
    report = ImportReport()
    existing = uploader.existing_slugs() if skip_existing else set()

    for recipe in recipes:
        if recipe.slug in existing:
            report.skipped.append(recipe.title)
            continue
        try:
            uploader.create(recipe)
            report.created.append(recipe.title)
        except httpx.HTTPError as exc:
            # One bad recipe must not end the run. Ninety succeeded imports and
            # a list of three failures is a good afternoon; an exception on
            # recipe four is a wasted one.
            logger.warning("failed to import %s: %s", recipe.title, exc)
            report.failed.append((recipe.title, str(exc)))
    return report
