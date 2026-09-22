#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Update Entity Metadata - Add complete information to universities and locations

Usage:
    python update_entities.py [--api-url URL] [--dry-run]
"""

import argparse
import sys
from typing import Dict, List, Optional

import requests

# Complete metadata for the 4 universities with incomplete data
UNIVERSITY_DATA = {
    "Technische Universität Berlin": {
        "long_name": "Technische Universität Berlin",
        "short_name": "TU Berlin",
        "type": "Technische Universität",
        "founded": 1879,
        "city": "Berlin",
        "state": "Berlin",
        "domain": "tu.berlin",
        "coordinates": [52.5125, 13.3267],
        "excellence": True,
        "tu9": True
    },
    "Humboldt-Universität zu Berlin": {
        "long_name": "Humboldt-Universität zu Berlin",
        "short_name": "HU Berlin",
        "type": "Universität",
        "founded": 1810,
        "city": "Berlin",
        "state": "Berlin",
        "domain": "hu-berlin.de",
        "coordinates": [52.5186, 13.3936],
        "excellence": True,
        "tu9": False
    },
    "Ludwig-Maximilians-Universität München": {
        "long_name": "Ludwig-Maximilians-Universität München",
        "short_name": "LMU München",
        "type": "Universität",
        "founded": 1472,
        "city": "München",
        "state": "Bayern",
        "domain": "lmu.de",
        "coordinates": [48.1506, 11.5810],
        "excellence": True,
        "tu9": False
    },
    "Ruprecht-Karls-Universität Heidelberg": {
        "long_name": "Ruprecht-Karls-Universität Heidelberg",
        "short_name": "Uni Heidelberg",
        "type": "Universität",
        "founded": 1386,
        "city": "Heidelberg",
        "state": "Baden-Württemberg",
        "domain": "uni-heidelberg.de",
        "coordinates": [49.4093, 8.6944],
        "excellence": True,
        "tu9": False
    }
}

# Complete metadata for the 2 cities with incomplete data
LOCATION_DATA = {
    "Berlin": {
        "long_name": "Berlin",
        "short_name": "Berlin",
        "type": "Bundeshauptstadt",
        "state": "Berlin",
        "country": "Deutschland",
        "population": 3700000,
        "area_km2": 892,
        "coordinates": [52.5200, 13.4050],
        "postal_codes": ["10115", "10117", "10119", "10178", "10179"],
        "founded": 1237
    },
    "München": {
        "long_name": "München",
        "short_name": "München",
        "type": "Landeshauptstadt",
        "state": "Bayern",
        "country": "Deutschland",
        "population": 1500000,
        "area_km2": 310,
        "coordinates": [48.1351, 11.5820],
        "postal_codes": ["80331", "80333", "80335", "80337", "80339"],
        "founded": 1158
    }
}


class EntityUpdater:
    """Update entity metadata via API"""

    def __init__(self, api_url: str, dry_run: bool = False):
        self.api_url = api_url.rstrip('/')
        self.dry_run = dry_run
        self.updated = 0
        self.failed = 0
        self.skipped = 0

    def fetch_entities(self, entity_type: str) -> List[Dict]:
        """Fetch all entities of given type"""
        try:
            response = requests.get(
                f"{self.api_url}/admin/entities",
                params={"entity_type": entity_type},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"✗ Failed to fetch {entity_type} entities: {e}")
            return []

    def update_entity(self, entity_id: int, canonical_name: str, metadata: Dict) -> bool:
        """Update entity metadata"""
        if self.dry_run:
            print(f"  [DRY-RUN] Would update entity {entity_id}: {canonical_name}")
            print(f"            New metadata: {metadata}")
            return True

        try:
            response = requests.put(
                f"{self.api_url}/admin/entities/{entity_id}",
                json={
                    "metadata": metadata
                },
                timeout=10
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"  ✗ Failed to update {canonical_name}: {e}")
            return False

    def process_universities(self):
        """Process and update universities"""
        print("\n" + "=" * 70)
        print("  UPDATING UNIVERSITY ENTITIES")
        print("=" * 70)

        entities = self.fetch_entities("university")
        print(f"ℹ Found {len(entities)} university entities\n")

        for entity in entities:
            entity_id = entity['id']
            canonical_name = entity['canonical_name']
            current_metadata = entity.get('metadata', {})

            # Check if we have complete data for this university
            if canonical_name in UNIVERSITY_DATA:
                new_metadata = UNIVERSITY_DATA[canonical_name]

                # Check if update is needed
                if self._needs_update(current_metadata, new_metadata):
                    print(f"  → Updating: {canonical_name}")
                    self._print_changes(current_metadata, new_metadata)

                    if self.update_entity(entity_id, canonical_name, new_metadata):
                        self.updated += 1
                        print(f"    ✓ Updated successfully\n")
                    else:
                        self.failed += 1
                        print()
                else:
                    print(f"  ○ Skipping: {canonical_name} (already complete)")
                    self.skipped += 1
            else:
                print(f"  ⚠ No data available for: {canonical_name}")
                self.skipped += 1

    def process_locations(self):
        """Process and update locations"""
        print("\n" + "=" * 70)
        print("  UPDATING LOCATION ENTITIES")
        print("=" * 70)

        entities = self.fetch_entities("location")
        print(f"ℹ Found {len(entities)} location entities\n")

        for entity in entities:
            entity_id = entity['id']
            canonical_name = entity['canonical_name']
            current_metadata = entity.get('metadata', {})

            # Check if we have complete data for this location
            if canonical_name in LOCATION_DATA:
                new_metadata = LOCATION_DATA[canonical_name]

                # Check if update is needed
                if self._needs_update(current_metadata, new_metadata):
                    print(f"  → Updating: {canonical_name}")
                    self._print_changes(current_metadata, new_metadata)

                    if self.update_entity(entity_id, canonical_name, new_metadata):
                        self.updated += 1
                        print(f"    ✓ Updated successfully\n")
                    else:
                        self.failed += 1
                        print()
                else:
                    print(f"  ○ Skipping: {canonical_name} (already complete)")
                    self.skipped += 1
            else:
                print(f"  ⚠ No data available for: {canonical_name}")
                self.skipped += 1

    def _needs_update(self, current: Dict, new: Dict) -> bool:
        """Check if entity needs update"""
        # If current is empty, definitely needs update
        if not current:
            return True

        # If current has fewer than 5 fields, probably incomplete
        if len(current) < 5:
            return True

        # Check if any key fields are missing or different
        key_fields = ['type', 'founded', 'coordinates', 'state']
        for field in key_fields:
            if field in new:
                if field not in current:
                    return True
                # Also update if coordinates are significantly different
                if field == 'coordinates' and current[field] != new[field]:
                    return True

        return False

    def _print_changes(self, current: Dict, new: Dict):
        """Print what will be changed"""
        if not current:
            print(f"    • Adding all metadata fields: {', '.join(new.keys())}")
            return

        missing_fields = [k for k in new.keys() if k not in current]
        if missing_fields:
            print(f"    • Adding fields: {', '.join(missing_fields)}")

        changed_fields = []
        for k in new.keys():
            if k in current and current[k] != new[k]:
                changed_fields.append(k)

        if changed_fields:
            print(f"    • Updating fields: {', '.join(changed_fields)}")

    def print_summary(self):
        """Print update summary"""
        print("\n" + "=" * 70)
        print("  UPDATE SUMMARY")
        print("=" * 70)
        print(f"  Updated:  {self.updated}")
        print(f"  Skipped:  {self.skipped}")
        print(f"  Failed:   {self.failed}")
        print("=" * 70)

        if self.dry_run:
            print("\n⚠ DRY-RUN mode - no changes were made")
            print("  Run without --dry-run to apply changes")
        elif self.updated > 0:
            print(f"\n✓ Successfully updated {self.updated} entities!")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="Update entity metadata with complete information"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )
    parser.add_argument(
        "--universities-only",
        action="store_true",
        help="Only update universities"
    )
    parser.add_argument(
        "--locations-only",
        action="store_true",
        help="Only update locations"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("  ENTITY METADATA UPDATE SCRIPT")
    print("=" * 70)
    print(f"  API URL: {args.api_url}")
    if args.dry_run:
        print("  Mode: DRY-RUN (no changes will be made)")
    print("=" * 70)

    # Check API connection
    print("ℹ Checking API connection...")
    try:
        response = requests.get(f"{args.api_url}/health", timeout=5)
        response.raise_for_status()
        print("✓ API is reachable")
    except Exception as e:
        print(f"✗ API is not reachable: {e}")
        sys.exit(1)

    # Update entities
    updater = EntityUpdater(args.api_url, dry_run=args.dry_run)

    if not args.locations_only:
        updater.process_universities()

    if not args.universities_only:
        updater.process_locations()

    updater.print_summary()

    sys.exit(0 if updater.failed == 0 else 1)


if __name__ == "__main__":
    main()