# pattern: Functional Core
from dataclasses import replace
from itertools import groupby

from pipeline.crawler.parser import ParsedDelivery
from pipeline.lexicons.models import Lexicon


def _group_key(delivery: ParsedDelivery) -> tuple[str, str]:
    """Extract grouping key from delivery: (workplan_id, dp_id)."""
    return (delivery.workplan_id, delivery.dp_id)


def _version_sort_key(delivery: ParsedDelivery) -> str:
    """Extract version for descending sort."""
    return delivery.version


def derive(
    deliveries: list[ParsedDelivery],
    lexicon: Lexicon,
) -> list[ParsedDelivery]:
    """Derive 'failed' status for pending deliveries superseded by newer versions.

    Within each (workplan_id, dp_id) group, any pending delivery that is NOT
    the highest version is marked as failed. Passed deliveries are never changed.

    Returns a new list — does not mutate the input.
    """
    if not deliveries:
        return []

    result = []
    sorted_deliveries = sorted(deliveries, key=_group_key)

    for _key, group in groupby(sorted_deliveries, key=_group_key):
        group_list = list(group)
        if len(group_list) == 1:
            result.append(group_list[0])
            continue

        by_version = sorted(group_list, key=_version_sort_key, reverse=True)
        highest_version = by_version[0].version

        for delivery in group_list:
            if delivery.status == "pending" and delivery.version != highest_version:
                result.append(replace(delivery, status="failed"))
            else:
                result.append(delivery)

    return result
