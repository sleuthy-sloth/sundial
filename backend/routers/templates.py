"""Templates: the list, the items in one, and putting a whole template on a day.

Seven routes around one idea — a day structure you wrote down and can use again. Nothing here is
automatic: a template is applied because somebody asked for it, to the day they named, and the
only way it reaches a day is this file. There is no recurring template, and no apply that was
not asked for.

Every refusal is a sentence, for the same reason `routers/routines.py` gives: the frontend has
nowhere else to get those words from. A template with nothing in it, an item with no title, a
colour outside the palette, an item that would run past midnight, a day that is not a day.

The item list is validated as a whole, not row by row as it arrives, so a bad third item refuses
the request before the first two have been written — the same shape `_rule` gives a routine.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from schemas.templates import ApplyIn, DuplicateIn, TemplateIn, TemplateItemsIn, TemplatePatch
from services import templates
from services.blocks import PALETTE
from services.scheduling import check_fits, validate_day

router = APIRouter()


def _name(raw: str) -> str:
    """A template's name, and the one thing the database insists on: that there is one."""
    name = str(raw).strip()
    if not name:
        raise HTTPException(400, "a template needs a name")
    return name


def _items(raw_items) -> list[dict]:
    """The items as they will be stored, checked together.

    `check_fits` is the only rule that needs more than one field, so it is the only one that
    could not have lived in the schema: an item that starts at 23:30 and lasts an hour is only
    wrong as a pair. An Anytime item is not checked against the day at all — it has no hour, so
    there is nothing for it to run past.

    The lines under an item are checked in the same pass, so a bad step refuses the request before
    any of it is written — the same shape the whole list already had.
    """
    items: list[dict] = []
    for index, item in enumerate(raw_items, start=1):
        title = str(item.title).strip()
        if not title:
            raise HTTPException(400, f"item {index} needs a title")
        # A colour left out gets the one a block's column defaults to, so a hand-written
        # request does not have to know this app's palette to add a line to a template. A
        # colour given has to be one of the eight, the same as everywhere else.
        color = item.color or "slate"
        if color not in PALETTE:
            raise HTTPException(400, f"unknown color {color!r}")
        if item.start_min is not None:
            check_fits(item.start_min, item.duration_min)
        lines: list[dict] = []
        for step, line in enumerate(item.subtasks, start=1):
            if not str(line.title).strip():
                raise HTTPException(400, f"item {index}, step {step} needs a title")
            lines.append({"title": str(line.title).strip(), "duration_min": line.duration_min})
        items.append(
            {
                "title": title,
                "start_min": item.start_min,
                "duration_min": item.duration_min,
                "color": color,
                "icon": str(item.icon).strip(),
                "notes": item.notes,
                "subtasks": lines,
            }
        )
    return items


@router.get("/api/templates")
def get_templates() -> dict:
    """Every template with its items, by name.

    All of them in one answer rather than a list plus a fetch per template: there are a handful,
    and the panel that manages them draws the contents of the one being edited.
    """
    return {"templates": templates.list_templates()}


@router.post("/api/templates", status_code=201)
def create_template(body: TemplateIn) -> dict:
    return templates.create_template(_name(body.name), _items(body.items))


@router.patch("/api/templates/{template_id}")
def patch_template(template_id: str, body: TemplatePatch) -> dict:
    """Rename. The items have their own route, because they are replaced as a whole list."""
    if body.name is None:
        return templates.get_template(template_id)
    return templates.rename_template(template_id, _name(body.name))


@router.delete("/api/templates/{template_id}", status_code=204)
def delete_template(template_id: str) -> None:
    """The template and its items. Days it was applied to are untouched — those are blocks."""
    templates.delete_template(template_id)


@router.put("/api/templates/{template_id}/blocks")
def put_template_items(template_id: str, body: TemplateItemsIn) -> dict:
    """Replace the whole ordered list.

    A PUT rather than a patch per item: the order is part of what is being saved, so the honest
    request is the list you ended up with. Sending it empty is how you empty a template — and
    the server will then refuse to apply it, which is a better answer than it existing with
    nothing in it and looking applicable.
    """
    return templates.put_items(template_id, _items(body.items))


@router.post("/api/templates/{template_id}/duplicate", status_code=201)
def duplicate_template(template_id: str, body: DuplicateIn | None = None) -> dict:
    """A copy you can then change, leaving the original as it was."""
    name = _name(body.name) if body and body.name is not None else None
    return templates.duplicate_template(template_id, name)


@router.post("/api/templates/{template_id}/apply")
def apply_template(template_id: str, body: ApplyIn) -> dict:
    """Add every item to one day, as blocks alongside whatever is already planned.

    Nothing existing is read, moved or replaced, and overlaps are left alone — two things at
    nine o'clock is a day that already had something at nine o'clock. The answer names the day
    and lists the block ids that were created, which is everything a caller needs to say what
    happened and, if it wants, to offer to take them back off again.
    """
    validate_day(body.day)
    return templates.apply_template(template_id, body.day)
