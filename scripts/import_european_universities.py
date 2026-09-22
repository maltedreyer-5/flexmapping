# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Import European universities into the entity inventory.

Source: the university-domains-list dataset, which supplies name, country and
domains for roughly 10,000 institutions worldwide. It supplies neither student
numbers nor coordinates, so this script writes neither. Fields the source does
not cover are left empty rather than estimated: the entity inventory is what
entity normalization matches against, and a wrong coordinate or a wrong city
would be silently wrong.

Institutions that the dataset omits are listed in EXTRA_ENTITIES below and are
imported alongside it.

Usage:
    python scripts/import_european_universities.py --user admin --password ...
    python scripts/import_european_universities.py --countries DE,AT,CH
    python scripts/import_european_universities.py --dry-run
"""
import argparse
import json
import sys
import urllib.request
from typing import Dict, List

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not found. Install it with: pip install requests")
    sys.exit(1)

SOURCE_URL = (
    "https://raw.githubusercontent.com/Hipo/university-domains-list/"
    "master/world_universities_and_domains.json"
)

# EU-27 plus EFTA plus the United Kingdom. Override with --countries.
DEFAULT_COUNTRIES = [
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
    "SE", "SI", "SK",                    # EU-27
    "CH", "IS", "LI", "NO",              # EFTA
    "GB",                                # United Kingdom
]

# Supranational and inter-governmental institutions that a country-based
# dataset does not carry, or carries under a name that is hard to match.
EXTRA_ENTITIES = [
    {
        "canonical_name": "European University Institute",
        "domains": ["eui.eu"],
        "country": "Italy",
        "alpha_two_code": "IT",
        "variants": ["EUI", "Istituto Universitario Europeo"],
    },
    {
        "canonical_name": "College of Europe",
        "domains": ["coleurope.eu"],
        "country": "Belgium",
        "alpha_two_code": "BE",
        "variants": ["Collège d'Europe"],
    },
    {
        "canonical_name": "European University Association",
        "domains": ["eua.eu"],
        "country": "Belgium",
        "alpha_two_code": "BE",
        "variants": ["EUA"],
    },
]


def fetch_source(url: str) -> List[Dict]:
    """Download the dataset."""
    print(f"Fetching {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        data = json.load(response)
    print(f"  {len(data)} institutions in the source")
    return data


def select(data: List[Dict], countries: List[str]) -> List[Dict]:
    """Filter by country code and normalise into the shape used below."""
    wanted = {c.strip().upper() for c in countries}
    out = []
    for item in data:
        if item.get("alpha_two_code") not in wanted:
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "canonical_name": name,
                "domains": item.get("domains") or [],
                "country": item.get("country"),
                "alpha_two_code": item.get("alpha_two_code"),
                "variants": [],
            }
        )
    return out


def create_entity(base_url: str, auth, entity: Dict) -> tuple[bool, str]:
    """Create one entity and its variants through the admin API."""
    payload = {
        "entity_type": "university",
        "canonical_name": entity["canonical_name"],
        "metadata": {
            "country": entity.get("country"),
            "country_code": entity.get("alpha_two_code"),
            "domain": entity["domains"][0] if entity["domains"] else None,
            "domains": entity["domains"],
            "source": "university-domains-list",
        },
    }

    try:
        response = requests.post(f"{base_url}/admin/entities", json=payload, auth=auth, timeout=30)
    except requests.RequestException as error:
        return False, str(error)

    if response.status_code == 401:
        return False, "authentication required: pass --user and --password"
    if response.status_code == 403:
        return False, "the account needs the admin role"
    if response.status_code == 500 and "already exists" in response.text.lower():
        return True, "already exists"
    if response.status_code not in (200, 201):
        return False, f"status {response.status_code}"

    entity_id = response.json()["id"]
    added = 0
    for variant in entity.get("variants", []):
        variant_response = requests.post(
            f"{base_url}/admin/entities/{entity_id}/variants",
            json={"variant_name": variant, "is_auto_detected": False},
            auth=auth,
            timeout=30,
        )
        if variant_response.status_code in (200, 201):
            added += 1

    return True, f"id {entity_id}, {added} variants"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import European universities into the entity inventory"
    )
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--user", help="account with the admin role")
    parser.add_argument("--password")
    parser.add_argument(
        "--countries",
        default=",".join(DEFAULT_COUNTRIES),
        help="comma-separated ISO 3166-1 alpha-2 codes",
    )
    parser.add_argument("--source", default=SOURCE_URL)
    parser.add_argument("--limit", type=int, help="import at most this many, for testing")
    parser.add_argument("--dry-run", action="store_true", help="list what would be imported")
    args = parser.parse_args()

    countries = [c.strip().upper() for c in args.countries.split(",") if c.strip()]

    data = fetch_source(args.source)
    selected = select(data, countries)
    extras = [e for e in EXTRA_ENTITIES if e["alpha_two_code"] in countries]

    # Where the source already carries an institution, merge the additional
    # variants and domains into that entry instead of creating a second one.
    # The EUI, for instance, appears in the source under the domain iue.it.
    by_name = {e["canonical_name"].lower(): e for e in selected}
    merged = 0
    remaining = []
    for extra in extras:
        existing = by_name.get(extra["canonical_name"].lower())
        if existing is None:
            remaining.append(extra)
            continue
        existing["variants"] = sorted(set(existing["variants"]) | set(extra["variants"]))
        existing["domains"] = sorted(set(existing["domains"]) | set(extra["domains"]))
        merged += 1
    extras = remaining

    entities = selected + extras
    if args.limit:
        entities = entities[: args.limit]

    per_country: Dict[str, int] = {}
    for entity in entities:
        code = entity.get("alpha_two_code") or "??"
        per_country[code] = per_country.get(code, 0) + 1

    print(f"\n{len(entities)} institutions selected across {len(per_country)} countries")
    print(f"  {len(extras)} added from EXTRA_ENTITIES, {merged} merged into source entries")
    for code, count in sorted(per_country.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {code}: {count}")

    if args.dry_run:
        print("\nDry run. First ten:")
        for entity in entities[:10]:
            domain = entity["domains"][0] if entity["domains"] else "-"
            print(f"  {entity['canonical_name'][:60]:62} {domain}")
        return 0

    if not args.user or not args.password:
        print("\nERROR: --user and --password are required. The entity endpoints "
              "need an account with the admin role.")
        return 1

    auth = (args.user, args.password)
    created = existing = failed = 0
    for index, entity in enumerate(entities, 1):
        ok, message = create_entity(args.url, auth, entity)
        if ok:
            if message == "already exists":
                existing += 1
            else:
                created += 1
        else:
            failed += 1
            print(f"  FAILED {entity['canonical_name'][:50]}: {message}")
            if "authentication" in message or "admin role" in message:
                return 1
        if index % 100 == 0:
            print(f"  {index}/{len(entities)} processed")

    print(f"\nCreated {created}, already present {existing}, failed {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
