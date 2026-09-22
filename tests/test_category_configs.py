# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
The category YAML files are the single source of truth for categories and
prompts. A malformed file would only surface at startup, inside a try/except
that logs and continues -- so it is checked here instead.
"""
import pytest
import yaml

from app.seed import validate_config
from tests.conftest import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "app" / "config" / "categories"
CONFIG_FILES = sorted(CONFIG_DIR.glob("*.yaml"))


def test_category_configs_exist():
    assert CONFIG_FILES, f"No category configuration found in {CONFIG_DIR}"


@pytest.mark.parametrize("path", CONFIG_FILES, ids=lambda p: p.name)
def test_config_is_valid(path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    is_valid, errors = validate_config(config)
    assert is_valid, f"{path.name}: " + "; ".join(errors)


@pytest.mark.parametrize("path", CONFIG_FILES, ids=lambda p: p.name)
def test_active_groups_exist_in_field_groups(path):
    """An active group with no field group renders an empty section."""
    category = yaml.safe_load(path.read_text(encoding="utf-8"))["category"]
    missing = set(category["active_groups"]) - set(category["field_groups"])
    assert not missing, f"{path.name}: active groups without fields: {sorted(missing)}"


@pytest.mark.parametrize("path", CONFIG_FILES, ids=lambda p: p.name)
def test_grouped_fields_have_a_prompt(path):
    """Every field listed in a group needs a prompt, or it stays empty."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    declared = {p["internal_name"] for p in config.get("prompts", [])}
    grouped = {f for fields in config["category"]["field_groups"].values() for f in fields}
    missing = grouped - declared
    assert not missing, f"{path.name}: fields without a prompt: {sorted(missing)}"


def test_i18n_categories_match_the_configuration():
    """
    The i18n `categories` block must name exactly the configured categories.

    It listed a category that had no configuration file and omitted one that
    did. Neither showed up anywhere: an unknown key is never looked up, and a
    missing one renders as an empty label on the generated site.
    """
    import yaml as _yaml

    configured = {
        _yaml.safe_load(p.read_text(encoding="utf-8"))["category"]["internal_name"]
        for p in CONFIG_FILES
    }
    for language in ("de", "en"):
        path = REPO_ROOT / "app" / "config" / "i18n" / f"{language}.yaml"
        listed = set(_yaml.safe_load(path.read_text(encoding="utf-8")).get("categories", {}))
        assert listed == configured, (
            f"{path.name}: only in i18n {sorted(listed - configured)}, "
            f"only in configuration {sorted(configured - listed)}"
        )


def test_the_category_definition_is_the_only_template_source():
    """
    A profile template comes from the category configuration and from nowhere
    else.

    A second source existed: nine Markdown files under app/templates/ that a
    hard-coded mapping loaded in preference to the configured template. For
    three of the four categories, editing the template in the YAML file
    therefore had no effect, and nothing reported that. One category was absent
    from the mapping and one mapping entry named a category that does not
    exist.
    """
    stray = sorted(p.name for p in (REPO_ROOT / "app" / "templates").rglob("steckbrief_*.md"))
    assert not stray, (
        "Markdown profile templates found beside the category configuration: "
        f"{stray}. The template belongs in the category YAML file."
    )

    source = (REPO_ROOT / "app" / "services" / "steckbrief_generator.py").read_text(encoding="utf-8")
    assert "template_map" not in source, (
        "steckbrief_generator.py maps categories to template files again. "
        "The template comes from category.steckbrief_template."
    )
