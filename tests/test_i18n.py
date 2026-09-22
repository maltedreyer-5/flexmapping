# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
The German and English string files must carry the same keys.

They had already drifted: en.yaml held a `fields` block of some forty entries
that de.yaml did not know at all. A missing key renders as an empty string on
the generated site, with nothing in the log.
"""
import yaml

from tests.conftest import REPO_ROOT

I18N_DIR = REPO_ROOT / "app" / "config" / "i18n"


def flatten(data, prefix=""):
    keys = set()
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            keys |= flatten(value, f"{path}.")
        else:
            keys.add(path)
    return keys


def test_language_files_have_the_same_keys():
    de = flatten(yaml.safe_load((I18N_DIR / "de.yaml").read_text(encoding="utf-8")))
    en = flatten(yaml.safe_load((I18N_DIR / "en.yaml").read_text(encoding="utf-8")))
    only_de = sorted(de - en)
    only_en = sorted(en - de)
    assert not only_de and not only_en, (
        f"Only in de.yaml: {only_de}\nOnly in en.yaml: {only_en}"
    )
