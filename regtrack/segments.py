"""Vehicle segments: the dashboard's four-level picker over vehicle-category codes and usage.

    Level 1 physical class   2W / 4W
    Level 2 category         PV (passenger, UNECE L / M) / CV (commercial, UNECE N; for 2W: goods-carrying use)
    Level 3 typology         the UNECE code (L1, L2 / L3, M1, N1)
    Level 4 subtype          Private / Transport (taxis, cabs, bike taxis) / goods

A selection is a path ("4W", "4W/PV", "4W/PV/M1", "4W/PV/M1/transport") and resolves to the category codes it covers
plus, where a node sets one, a usage: a regulation applies when it names one of the codes (or ALL) and its usage is
unset, 'all' or the selected one - the same rule as /vehicles/applicable. Two-wheeler codes are the country's in-scope
L codes (India L1/L2; Thailand and Malaysia L1/L3, see IN_SCOPE_CATEGORIES_BY_COUNTRY).
"""

from __future__ import annotations

from regtrack.models.enums import Usage, in_scope_categories

USAGES = {Usage.PRIVATE.value, Usage.TRANSPORT.value}


def tree(cc: str | None, labels: dict[str, str]) -> list[dict]:
    """The picker for one country; `labels` maps a code to its display label."""
    scope = sorted(in_scope_categories(cc) - {"ALL"})
    two = [c for c in scope if c.startswith("L")]

    def code(c: str, subtypes: list[dict]) -> dict:
        return {"key": c, "label": labels.get(c, c), "children": subtypes}

    private = {"key": "private", "label": "Private (personal)", "usage": "private"}
    return [
        {
            "key": "2W",
            "label": "2-Wheeler (2W)",
            "children": [
                {
                    "key": "PV",
                    "label": "Passenger (PV)",
                    "children": [
                        code(
                            c, [private, {"key": "transport", "label": "Transport (bike taxis)", "usage": "transport"}]
                        )
                        for c in two
                    ],
                },
                {
                    "key": "CV",
                    "label": "Commercial (CV)",
                    "usage": "transport",
                    "children": [code(c, [{"key": "goods", "label": "Delivery / cargo"}]) for c in two],
                },
            ],
        },
        {
            "key": "4W",
            "label": "4-Wheeler (4W)",
            "children": [
                {
                    "key": "PV",
                    "label": "Passenger (PV / M)",
                    "children": [
                        code(
                            "M1",
                            [private, {"key": "transport", "label": "Transport (taxis / cabs)", "usage": "transport"}],
                        )
                    ],
                },
                {
                    "key": "CV",
                    "label": "Commercial (CV / N)",
                    "children": [code("N1", [{"key": "goods", "label": "Cargo vans / light pickups"}])],
                },
            ],
        },
    ]


def resolve(cc: str | None, path: str | None) -> tuple[list[str], str | None] | None:
    """(codes, usage) of a segment path; None for an empty path. ValueError for a path not in the tree."""
    keys = [k for k in (path or "").strip("/").split("/") if k]
    if not keys:
        return None
    nodes, usage, node = tree(cc, {}), None, None
    for k in keys:
        node = next((n for n in nodes if n["key"].upper() == k.upper()), None)
        if node is None:
            raise ValueError(f"unknown vehicle segment {path!r}")
        usage = node.get("usage", usage)
        nodes = node.get("children", [])

    def codes(n: dict, depth: int) -> set[str]:  # level 3 nodes are the codes
        if depth == 3:
            return {n["key"]}
        return set().union(*(codes(c, depth + 1) for c in n.get("children", [])))

    return sorted(codes(node, len(keys)) if len(keys) <= 3 else {keys[2].upper()}), usage


def label(path: str | None) -> str:
    """ "4W/PV/M1/transport" -> "4W-PV · M1 · transport" (the dashboard's segmentLabel)."""
    keys = [k for k in (path or "").strip("/").split("/") if k]
    return " · ".join(["-".join(keys[:2]), *keys[2:]]) if keys else ""


def usage_sql(alias: str, usage: str | None) -> str:
    """SQL condition (with a leading AND) keeping rows whose usage fits; '' when no usage is selected."""
    if not usage:
        return ""
    if usage not in USAGES:
        raise ValueError(f"unknown usage {usage!r}")
    return f" AND ({alias}.usage = '{{}}' OR {alias}.usage && ARRAY['{usage}','all'])"
