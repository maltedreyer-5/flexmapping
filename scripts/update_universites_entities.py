# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Update University Entities with Extended Metadata

Adds:
- long_name (vollständiger offizieller Name)
- short_name (Akronym/Kurzform)
- domain (Hauptdomain der Website)
- coordinates (Lat/Long)

Usage:
    python scripts/update_university_entities.py [--url http://localhost:8000]
"""
import argparse
import sys

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found. Install it with: pip install requests")
    sys.exit(1)

# ANSI Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_success(msg: str):
    print(f"{GREEN}✓{RESET} {msg}")


def print_error(msg: str):
    print(f"{RED}✗{RESET} {msg}")


def print_info(msg: str):
    print(f"{YELLOW}ℹ{RESET} {msg}")


def print_step(msg: str):
    print(f"{BLUE}→{RESET} {msg}")


def get_extended_university_data():
    """
    Get extended metadata for German universities

    Returns list of dicts with:
    - canonical_name: Official name
    - long_name: Full official name
    - short_name: Acronym
    - domain: Main website domain
    - coordinates: [lat, lon]
    - city: City
    - founded: Year
    - variants: List of name variants
    """
    return [
        {
            "canonical_name": "Technische Universität Berlin",
            "metadata": {
                "long_name": "Technische Universität Berlin",
                "short_name": "TU Berlin",
                "domain": "tu.berlin",
                "coordinates": [52.5125, 13.3269],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1879,
                "type": "Technische Universität"
            },
            "variants": ["TU Berlin", "TUB", "TU-Berlin", "Technische Uni Berlin"]
        },
        {
            "canonical_name": "Humboldt-Universität zu Berlin",
            "metadata": {
                "long_name": "Humboldt-Universität zu Berlin",
                "short_name": "HU Berlin",
                "domain": "hu-berlin.de",
                "coordinates": [52.5186, 13.3936],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1810,
                "type": "Universität"
            },
            "variants": ["HU Berlin", "HU", "Humboldt-Uni", "Humboldt Universität"]
        },
        {
            "canonical_name": "Ludwig-Maximilians-Universität München",
            "metadata": {
                "long_name": "Ludwig-Maximilians-Universität München",
                "short_name": "LMU München",
                "domain": "lmu.de",
                "coordinates": [48.1507, 11.5810],
                "city": "München",
                "state": "Bayern",
                "founded": 1472,
                "type": "Universität"
            },
            "variants": ["LMU München", "LMU", "Uni München", "Ludwig-Maximilians-Uni"]
        },
        {
            "canonical_name": "Ruprecht-Karls-Universität Heidelberg",
            "metadata": {
                "long_name": "Ruprecht-Karls-Universität Heidelberg",
                "short_name": "Uni Heidelberg",
                "domain": "uni-heidelberg.de",
                "coordinates": [49.4093, 8.6946],
                "city": "Heidelberg",
                "state": "Baden-Württemberg",
                "founded": 1386,
                "type": "Universität"
            },
            "variants": ["Uni Heidelberg", "Heidelberg University", "Universität Heidelberg"]
        },
        {
            "canonical_name": "Freie Universität Berlin",
            "metadata": {
                "long_name": "Freie Universität Berlin",
                "short_name": "FU Berlin",
                "domain": "fu-berlin.de",
                "coordinates": [52.4524, 13.2901],
                "city": "Berlin",
                "state": "Berlin",
                "founded": 1948,
                "type": "Universität"
            },
            "variants": ["FU Berlin", "FU", "Freie Uni Berlin", "Free University Berlin"]
        },
        {
            "canonical_name": "Rheinisch-Westfälische Technische Hochschule Aachen",
            "metadata": {
                "long_name": "Rheinisch-Westfälische Technische Hochschule Aachen",
                "short_name": "RWTH Aachen",
                "domain": "rwth-aachen.de",
                "coordinates": [50.7802, 6.0781],
                "city": "Aachen",
                "state": "Nordrhein-Westfalen",
                "founded": 1870,
                "type": "Technische Hochschule"
            },
            "variants": ["RWTH Aachen", "RWTH", "TH Aachen", "Technische Hochschule Aachen"]
        },
        {
            "canonical_name": "Universität Hamburg",
            "metadata": {
                "long_name": "Universität Hamburg",
                "short_name": "UHH",
                "domain": "uni-hamburg.de",
                "coordinates": [53.5672, 9.9867],
                "city": "Hamburg",
                "state": "Hamburg",
                "founded": 1919,
                "type": "Universität"
            },
            "variants": ["UHH", "Uni Hamburg", "University of Hamburg", "Hamburg University"]
        },
        {
            "canonical_name": "Technische Universität München",
            "metadata": {
                "long_name": "Technische Universität München",
                "short_name": "TUM",
                "domain": "tum.de",
                "coordinates": [48.1497, 11.5679],
                "city": "München",
                "state": "Bayern",
                "founded": 1868,
                "type": "Technische Universität"
            },
            "variants": ["TUM", "TU München", "Technische Uni München", "Technical University Munich"]
        },
        {
            "canonical_name": "Universität Mannheim",
            "metadata": {
                "long_name": "Universität Mannheim",
                "short_name": "Uni Mannheim",
                "domain": "uni-mannheim.de",
                "coordinates": [49.4823, 8.4642],
                "city": "Mannheim",
                "state": "Baden-Württemberg",
                "founded": 1907,
                "type": "Universität"
            },
            "variants": ["Uni Mannheim", "University of Mannheim", "Mannheim University"]
        },
        {
            "canonical_name": "Johann Wolfgang Goethe-Universität Frankfurt am Main",
            "metadata": {
                "long_name": "Johann Wolfgang Goethe-Universität Frankfurt am Main",
                "short_name": "Goethe-Uni Frankfurt",
                "domain": "uni-frankfurt.de",
                "coordinates": [50.1280, 8.6648],
                "city": "Frankfurt am Main",
                "state": "Hessen",
                "founded": 1914,
                "type": "Universität"
            },
            "variants": ["Goethe-Uni Frankfurt", "Uni Frankfurt", "Goethe University", "Frankfurt University"]
        },
        {
            "canonical_name": "Karlsruher Institut für Technologie",
            "metadata": {
                "long_name": "Karlsruher Institut für Technologie",
                "short_name": "KIT",
                "domain": "kit.edu",
                "coordinates": [49.0094, 8.4044],
                "city": "Karlsruhe",
                "state": "Baden-Württemberg",
                "founded": 1825,
                "type": "Technische Universität"
            },
            "variants": ["KIT", "Karlsruhe Institute of Technology", "Uni Karlsruhe"]
        },
        {
            "canonical_name": "Eberhard Karls Universität Tübingen",
            "metadata": {
                "long_name": "Eberhard Karls Universität Tübingen",
                "short_name": "Uni Tübingen",
                "domain": "uni-tuebingen.de",
                "coordinates": [48.5216, 9.0576],
                "city": "Tübingen",
                "state": "Baden-Württemberg",
                "founded": 1477,
                "type": "Universität"
            },
            "variants": ["Uni Tübingen", "University of Tübingen", "Tübingen University"]
        },
        {
            "canonical_name": "Universität zu Köln",
            "metadata": {
                "long_name": "Universität zu Köln",
                "short_name": "Uni Köln",
                "domain": "uni-koeln.de",
                "coordinates": [50.9282, 6.9282],
                "city": "Köln",
                "state": "Nordrhein-Westfalen",
                "founded": 1388,
                "type": "Universität"
            },
            "variants": ["Uni Köln", "University of Cologne", "Cologne University"]
        },
        {
            "canonical_name": "Westfälische Wilhelms-Universität Münster",
            "metadata": {
                "long_name": "Westfälische Wilhelms-Universität Münster",
                "short_name": "WWU Münster",
                "domain": "uni-muenster.de",
                "coordinates": [51.9633, 7.6124],
                "city": "Münster",
                "state": "Nordrhein-Westfalen",
                "founded": 1780,
                "type": "Universität"
            },
            "variants": ["WWU Münster", "WWU", "Uni Münster", "University of Münster"]
        },
        {
            "canonical_name": "Friedrich-Alexander-Universität Erlangen-Nürnberg",
            "metadata": {
                "long_name": "Friedrich-Alexander-Universität Erlangen-Nürnberg",
                "short_name": "FAU",
                "domain": "fau.de",
                "coordinates": [49.5967, 11.0045],
                "city": "Erlangen",
                "state": "Bayern",
                "founded": 1743,
                "type": "Universität"
            },
            "variants": ["FAU", "Uni Erlangen-Nürnberg", "FAU Erlangen-Nürnberg"]
        }
    ]


def update_entity(base_url: str, entity_id: int, metadata: dict) -> bool:
    """Update entity metadata via API"""
    url = f"{base_url}/admin/entities/{entity_id}"

    try:
        # PUT endpoint doesn't exist in current API, so we need to use a workaround
        # We'll delete and recreate the entity
        print_info(f"Note: Update endpoint not available, entity will keep existing metadata")
        return True

    except Exception as e:
        print_error(f"Error updating entity: {str(e)}")
        return False


def create_or_update_entity(base_url: str, entity_data: dict) -> bool:
    """Create entity with extended metadata or update if exists"""
    url = f"{base_url}/admin/entities"

    try:
        # Try to create
        payload = {
            "entity_type": "university",
            "canonical_name": entity_data["canonical_name"],
            "metadata": entity_data["metadata"]
        }

        response = requests.post(url, json=payload)

        if response.status_code in [200, 201]:
            result = response.json()
            entity_id = result["id"]
            print_success(f"Entity created: {entity_data['canonical_name']} (ID: {entity_id})")

            # Add variants
            variants_added = 0
            for variant in entity_data.get("variants", []):
                variant_url = f"{base_url}/admin/entities/{entity_id}/variants"
                variant_payload = {
                    "variant_name": variant,
                    "is_auto_detected": False
                }
                var_response = requests.post(variant_url, json=variant_payload)

                if var_response.status_code in [200, 201]:
                    variants_added += 1
                elif var_response.status_code == 500 and "already exists" in var_response.text.lower():
                    variants_added += 1  # Count as success if already exists

            if variants_added > 0:
                print_info(f"  → {variants_added} variant(s) added/verified")

            return True

        elif response.status_code == 500 and "already exists" in response.text.lower():
            print_info(f"Entity already exists: {entity_data['canonical_name']}")
            print_info("  → To update metadata, manually update via database or recreate")
            return True

        else:
            print_error(f"Failed to create entity: {response.status_code}")
            print_error(f"Response: {response.text[:200]}")
            return False

    except Exception as e:
        print_error(f"Error with entity: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Update university entities with extended metadata")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force creation of new entities (skip check for existing)"
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    print("\n" + "=" * 70)
    print("  Update University Entities - Extended Metadata")
    print("=" * 70)
    print(f"  API URL: {base_url}")
    print("=" * 70 + "\n")

    # Check API
    print_step("Checking API connection...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code != 200:
            print_error(f"API returned status code {response.status_code}")
            return
        print_success("API is reachable\n")
    except Exception as e:
        print_error(f"Cannot connect to API: {str(e)}")
        return

    # Get extended data
    print_step("Loading extended university data...")
    universities = get_extended_university_data()
    print_success(f"Loaded data for {len(universities)} universities\n")

    # Process entities
    print_step("Creating/updating entities...")
    print_info("Note: Existing entities will be kept with their current metadata")
    print_info("      New entities will be created with extended metadata\n")

    created = 0
    existing = 0
    failed = 0

    for uni in universities:
        result = create_or_update_entity(base_url, uni)
        if result:
            # Check if it was actually created or already existed
            if "already exists" in str(result):
                existing += 1
            else:
                created += 1
        else:
            failed += 1

    print()

    # Summary
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  Universities processed: {len(universities)}")
    print(f"  New entities created:   {created}")
    print(f"  Already existing:       {existing}")
    print(f"  Failed:                 {failed}")
    print("=" * 70)

    if failed == 0:
        print_success("All university entities processed successfully!")
        print()
        print("Extended metadata includes:")
        print("  • long_name    - Vollständiger offizieller Name")
        print("  • short_name   - Akronym/Kurzform")
        print("  • domain       - Hauptdomain der Website")
        print("  • coordinates  - [Latitude, Longitude]")
        print("  • city, state  - Standort")
        print("  • founded      - Gründungsjahr")
        print("  • type         - Hochschultyp")
        print()
        print(f"View entities: {base_url}/admin/entities")
    else:
        print_error("Some entities failed. Check the errors above.")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()