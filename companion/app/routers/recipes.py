"""Recipe scaling — the one recipe operation Companion owns.

Everything else about recipes goes straight to Mealie: the app searches Mealie
directly and so does the MCP server, because proxying search would mean
reimplementing pagination and tag filtering for no gain. Scaling is different —
three consumers need identical arithmetic, so it lives here once.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth import CurrentPrincipal
from app.mealie import MealieClient, get_mealie
from app.scaling import scale_recipe

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.get("/{slug}/scaled")
def scaled_recipe(
    slug: str,
    principal: CurrentPrincipal,
    mealie: Annotated[MealieClient, Depends(get_mealie)],
    servings: Annotated[int | None, Query(gt=0, le=99)] = None,
) -> dict:
    """Ingredients multiplied to a serving count, with per-line honesty.

    Omitting `servings` returns the recipe at its own scale — still useful,
    because the response shape is the one the client renders either way and
    `factor: 1.0` needs no special case in the app.

    `scalable: false` means the recipe never says what it yields, so there is
    nothing to multiply against. The app shows the ingredients and hides the
    stepper rather than pretending a base of 4.
    """
    del principal  # auth only — recipes aren't tenant-scoped, Mealie is shared
    recipe = mealie.get_recipe(slug)
    return scale_recipe(recipe, servings)
