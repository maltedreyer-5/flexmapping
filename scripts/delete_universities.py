# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Delete All University Entities

DANGER: This will delete ALL entities of type 'university'!

Usage:
    python scripts/delete_all_universities.py [--url http://localhost:8000] [--confirm]
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
BOLD = '\033[1m'
RESET = '\033[0m'


def print_success(msg: str):
    print(f"{GREEN}✓{RESET} {msg}")


def print_error(msg: str):
    print(f"{RED}✗{RESET} {msg}")


def print_warning(msg: str):
    print(f"{YELLOW}⚠{RESET} {msg}")


def print_info(msg: str):
    print(f"{BLUE}ℹ{RESET} {msg}")


def get_all_universities(base_url: str):
    """Get all university entities"""
    url = f"{base_url}/admin/entities"

    try:
        response = requests.get(url, params={"entity_type": "university"})
        if response.status_code == 200:
            return response.json()
        else:
            print_error(f"Failed to fetch entities: {response.status_code}")
            return []
    except Exception as e:
        print_error(f"Error fetching entities: {str(e)}")
        return []


def delete_entity(base_url: str, entity_id: int, name: str) -> bool:
    """Delete a single entity"""
    url = f"{base_url}/admin/entities/{entity_id}"

    try:
        response = requests.delete(url)

        if response.status_code in [200, 204]:
            print_success(f"Deleted: {name} (ID: {entity_id})")
            return True
        else:
            print_error(f"Failed to delete {name}: {response.status_code}")
            return False

    except Exception as e:
        print_error(f"Error deleting {name}: {str(e)}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Delete all university entities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
WARNING: This will permanently delete all university entities!

Example:
    python scripts/delete_all_universities.py --confirm
        """
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm deletion (required to proceed)"
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    print("\n" + "=" * 70)
    print(f"{BOLD}  DELETE ALL UNIVERSITY ENTITIES{RESET}")
    print("=" * 70)
    print(f"  API URL: {base_url}")
    print("=" * 70 + "\n")

    # Check API
    print_info("Checking API connection...")
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code != 200:
            print_error(f"API returned status code {response.status_code}")
            return
        print_success("API is reachable\n")
    except Exception as e:
        print_error(f"Cannot connect to API: {str(e)}")
        return

    # Get all universities
    print_info("Fetching all university entities...")
    universities = get_all_universities(base_url)

    if not universities:
        print_info("No university entities found.")
        return

    print_success(f"Found {len(universities)} university entities\n")

    # Show what will be deleted
    print("=" * 70)
    print("THE FOLLOWING ENTITIES WILL BE DELETED:")
    print("=" * 70)
    for uni in universities[:10]:  # Show first 10
        print(f"  • {uni['canonical_name']} (ID: {uni['id']})")

    if len(universities) > 10:
        print(f"  ... and {len(universities) - 10} more")
    print("=" * 70 + "\n")

    # Safety check
    if not args.confirm:
        print_warning("SAFETY CHECK: --confirm flag not provided")
        print_warning("This operation will DELETE ALL university entities!")
        print()
        print("To proceed, run:")
        print(f"  python scripts/delete_all_universities.py --confirm")
        print()
        return

    # Final confirmation
    print_warning(f"You are about to DELETE {len(universities)} university entities!")
    print_warning("This action CANNOT be undone!")
    print()

    confirmation = input(f"{YELLOW}Type 'DELETE' to confirm:{RESET} ")

    if confirmation != "DELETE":
        print()
        print_info("Deletion cancelled.")
        return

    print()
    print_info("Starting deletion...")
    print()

    # Delete all entities
    deleted = 0
    failed = 0

    for uni in universities:
        if delete_entity(base_url, uni['id'], uni['canonical_name']):
            deleted += 1
        else:
            failed += 1

    print()

    # Summary
    print("=" * 70)
    print("  DELETION SUMMARY")
    print("=" * 70)
    print(f"  Total entities:  {len(universities)}")
    print(f"  Deleted:         {deleted}")
    print(f"  Failed:          {failed}")
    print("=" * 70)

    if failed == 0:
        print_success("All university entities deleted successfully!")
    else:
        print_warning(f"{failed} entities failed to delete. Check errors above.")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()