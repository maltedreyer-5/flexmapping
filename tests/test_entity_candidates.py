# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Candidate selection for entity normalization.

The prompt can carry only a limited number of entities. Before this selection
existed, it carried whatever the database returned first. With an inventory of
a few dozen entities that was the whole inventory; with a few thousand, which
the European import produces, it is an arbitrary slice that need not contain
the right answer at all.
"""
from types import SimpleNamespace

import pytest

from tests.conftest import REPO_ROOT  # noqa: F401  (sets sys.path)
from app.services.entity_normalizer import EntityNormalizerService


def entity(name, *variants):
    return SimpleNamespace(
        canonical_name=name,
        variants=[SimpleNamespace(variant_name=v) for v in variants],
    )


@pytest.fixture
def service():
    return EntityNormalizerService.__new__(EntityNormalizerService)


REAL = [
    entity("Technische Universität München", "TUM", "TU München"),
    entity("Technische Universität Berlin", "TU Berlin"),
    entity("Ludwig-Maximilians-Universität München", "LMU"),
    entity("Universität Wien", "Uni Wien"),
    entity("European University Institute", "EUI"),
]


def large_inventory(target):
    """The target sits at the very end, where a naive slice would never reach."""
    return [entity(f"University of Placeholder {i}") for i in range(2000)] + [target]


@pytest.mark.parametrize(
    "query",
    ["TU München", "TUM", "Technische Universität München", "Techn. Univ. Muenchen"],
)
def test_target_is_selected_from_a_large_inventory(service, query):
    target = entity("Technische Universität München", "TUM", "TU München")
    selected = service._select_candidates(query, large_inventory(target))
    assert len(selected) == service.MAX_PROMPT_CANDIDATES
    assert target in selected


def test_small_inventory_is_passed_through_unchanged(service):
    assert service._select_candidates("anything", REAL) == REAL


def test_abbreviation_matches_through_a_variant(service):
    target = entity("European University Institute", "EUI")
    selected = service._select_candidates("EUI", large_inventory(target))
    assert selected[0] is target


def test_ordering_puts_the_closest_first(service):
    padded = REAL + [entity(f"Filler {i}") for i in range(60)]
    selected = service._select_candidates("TU Berlin", padded)
    assert selected[0].canonical_name == "Technische Universität Berlin"


def test_selection_does_not_decide(service):
    """
    An unrelated query still yields a full candidate list. The pre-filter
    narrows the prompt; it does not rule a match in or out. That decision
    belongs to the model, and below the confidence threshold to a reviewer.
    """
    selected = service._select_candidates("Bäckerei Schmidt", large_inventory(REAL[0]))
    assert len(selected) == service.MAX_PROMPT_CANDIDATES
