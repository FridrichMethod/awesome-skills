#!/usr/bin/env python3
"""Validate a declared QMS applicability and scope intake.

The script checks whether accountable humans documented decisions and evidence. It
does not decide whether a law, regulation, standard, or conformity route applies.
"""

from __future__ import annotations

from typing import Any

from _common import (
    Review,
    finish,
    guarded_main,
    load_json,
    require_root_object,
    standard_parser,
)

ACTIVITIES = {
    "design-and-development",
    "manufacturing",
    "contract-manufacturing",
    "sterilization",
    "packaging-and-labeling",
    "storage",
    "distribution",
    "installation",
    "servicing",
    "software-development",
    "complaint-handling",
    "postmarket-surveillance",
    "regulatory-reporting",
}
APPLICABILITY = {"applicable", "not-applicable", "undetermined"}


def _text_list(
    review: Review,
    value: Any,
    path: str,
    *,
    allowed: set[str] | None = None,
    min_items: int = 1,
) -> list[str]:
    raw = review.list(value, path, min_items=min_items)
    if raw is None:
        return []
    result: list[str] = []
    for index, item in enumerate(raw):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str) or not item.strip():
            review.add("TEXT_REQUIRED", item_path, "requires non-empty text")
            continue
        if allowed is not None and item not in allowed:
            review.add(
                "VALUE_UNKNOWN",
                item_path,
                f"must be one of: {', '.join(sorted(allowed))}",
            )
            continue
        result.append(item)
    if len(result) != len(set(result)):
        review.add("VALUE_DUPLICATE", path, "must not contain duplicate values")
    return result


def validate(data: dict[str, Any]) -> tuple[Review, dict[str, int]]:
    review = Review()

    metadata = review.object(data.get("metadata"), "metadata")
    if metadata is not None:
        review.controlled_item(metadata, "metadata", require_approved=True)
        review.text(metadata, "intake_id", "metadata", max_chars=120)
        review.date(metadata, "review_date", "metadata")

    organization = review.object(data.get("organization"), "organization")
    if organization is not None:
        review.text(organization, "legal_name", "organization", max_chars=300)
        review.text(
            organization,
            "declared_lifecycle_role",
            "organization",
            max_chars=300,
        )
        review.text(
            organization,
            "authorized_management_representative",
            "organization",
            max_chars=200,
        )
        review.text(organization, "raqa_owner", "organization", max_chars=200)
        review.text(
            organization,
            "applicability_decision_owner",
            "organization",
            max_chars=200,
        )

    scope = review.object(data.get("scope"), "scope")
    sites: list[Any] = []
    products: list[Any] = []
    markets: list[Any] = []
    if scope is not None:
        _text_list(
            review,
            scope.get("lifecycle_activities"),
            "scope.lifecycle_activities",
            allowed=ACTIVITIES,
        )

        sites = review.list(scope.get("sites"), "scope.sites", min_items=1) or []
        for index, item in enumerate(sites):
            path = f"scope.sites[{index}]"
            site = review.object(item, path)
            if site is None:
                continue
            review.text(site, "id", path, max_chars=120)
            review.text(site, "name", path, max_chars=300)
            review.text(site, "address", path, max_chars=500)
            _text_list(
                review,
                site.get("activities"),
                f"{path}.activities",
                allowed=ACTIVITIES,
            )
            review.controlled_item(site, path, require_approved=True)
        review.unique_ids(sites, "scope.sites")

        products = (
            review.list(scope.get("products"), "scope.products", min_items=1) or []
        )
        for index, item in enumerate(products):
            path = f"scope.products[{index}]"
            product = review.object(item, path)
            if product is None:
                continue
            review.text(product, "id", path, max_chars=120)
            review.text(product, "family", path, max_chars=300)
            review.text(product, "intended_use", path, max_chars=2_000)
            review.text(
                product,
                "classification_or_rationale",
                path,
                max_chars=1_000,
            )
            _text_list(review, product.get("market_ids"), f"{path}.market_ids")
            review.controlled_item(product, path, require_approved=True)
        review.unique_ids(products, "scope.products")

        markets = review.list(scope.get("markets"), "scope.markets", min_items=1) or []
        for index, item in enumerate(markets):
            path = f"scope.markets[{index}]"
            market = review.object(item, path)
            if market is None:
                continue
            review.text(market, "id", path, max_chars=120)
            review.text(market, "jurisdiction", path, max_chars=300)
            decision = review.choice(
                market,
                "applicability",
                APPLICABILITY,
                path,
            )
            if decision == "undetermined":
                review.add(
                    "HUMAN_DECISION_REQUIRED",
                    f"{path}.applicability",
                    "authorized RA/QA or legal review must resolve applicability",
                    "blocker",
                )
            review.text(market, "decision_rationale", path, max_chars=2_000)
            review.controlled_item(market, path, require_approved=True)
        review.unique_ids(markets, "scope.markets")

        outsourced = review.list(
            scope.get("outsourced_processes"),
            "scope.outsourced_processes",
            min_items=0,
        )
        if outsourced is not None:
            for index, item in enumerate(outsourced):
                path = f"scope.outsourced_processes[{index}]"
                process = review.object(item, path)
                if process is None:
                    continue
                review.text(process, "id", path, max_chars=120)
                review.text(process, "process", path, max_chars=300)
                review.text(process, "provider", path, max_chars=300)
                review.text(process, "control_strategy", path, max_chars=2_000)
                review.controlled_item(process, path, require_approved=True)
            review.unique_ids(outsourced, "scope.outsourced_processes")

    return review, {
        "markets": len(markets),
        "products": len(products),
        "sites": len(sites),
    }


def main() -> int:
    parser = standard_parser(
        "Validate a local QMS scope/applicability intake without deciding applicability.",
        "Path to the local scope-intake JSON file",
    )
    args = parser.parse_args()
    data = require_root_object(load_json(args.input))
    review, metrics = validate(data)
    return finish("validate_scope_intake", review, args, metrics=metrics)


if __name__ == "__main__":
    guarded_main(main)
