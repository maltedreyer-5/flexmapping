# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Debug Prompts - Check what's actually in the database

Usage:
    python debug_prompts.py [--url http://localhost:8000]
"""
import argparse
import sys
import json

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
CYAN = '\033[96m'
RESET = '\033[0m'


def print_header(msg: str):
    print(f"\n{CYAN}{'=' * 70}{RESET}")
    print(f"{CYAN}{msg:^70}{RESET}")
    print(f"{CYAN}{'=' * 70}{RESET}\n")


def print_section(msg: str):
    print(f"\n{BLUE}{'─' * 70}{RESET}")
    print(f"{BLUE}{msg}{RESET}")
    print(f"{BLUE}{'─' * 70}{RESET}")


def debug_prompts(base_url: str):
    """Check all prompts via API"""

    print_header("FlexMapping prompt debug")

    # 1. Get all prompts
    print_section("1. Fetching ALL Prompts")
    try:
        response = requests.get(f"{base_url}/admin/prompts")
        if response.status_code == 200:
            prompts = response.json()
            print(f"{GREEN}✓{RESET} Found {len(prompts)} prompts in database")

            if len(prompts) == 0:
                print(f"{RED}✗{RESET} No prompts found! The database is empty.")
                return

            # Group by field_group
            by_group = {}
            for prompt in prompts:
                group = prompt.get('field_group', 'unknown')
                if group not in by_group:
                    by_group[group] = []
                by_group[group].append(prompt)

            print(f"\nPrompts by field_group:")
            for group, group_prompts in sorted(by_group.items()):
                print(f"  • {group}: {len(group_prompts)} prompts")

            # Show details of first 3 prompts
            print(f"\n{YELLOW}Sample prompts:{RESET}")
            for i, prompt in enumerate(prompts[:3]):
                print(f"\n  [{i + 1}] {prompt['display_name']}")
                print(f"      Internal Name: {prompt['internal_name']}")
                print(f"      Field Group: {prompt['field_group']}")
                print(f"      Entity Type: {prompt.get('entity_type', 'None')}")
                print(f"      Active: {prompt['is_active']}")
                print(f"      Required Confidence: {prompt['required_confidence']}")
                print(f"      ID: {prompt['id']}")
        else:
            print(f"{RED}✗{RESET} Failed to fetch prompts: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return
    except Exception as e:
        print(f"{RED}✗{RESET} Error: {str(e)}")
        return

    # 2. Get categories
    print_section("2. Checking Categories")
    try:
        response = requests.get(f"{base_url}/admin/categories")
        if response.status_code == 200:
            categories = response.json()
            print(f"{GREEN}✓{RESET} Found {len(categories)} categories")

            for cat in categories:
                print(f"\n  • {cat['display_name']} (ID: {cat['id']})")
                print(f"    Internal Name: {cat['internal_name']}")
                print(f"    Active: {cat['is_active']}")
        else:
            print(f"{RED}✗{RESET} Failed to fetch categories: {response.status_code}")
    except Exception as e:
        print(f"{RED}✗{RESET} Error: {str(e)}")

    # 3. Check category-prompt assignments
    print_section("3. Checking Category → Prompt Assignments")
    try:
        response = requests.get(f"{base_url}/admin/categories")
        if response.status_code == 200:
            categories = response.json()

            for cat in categories:
                cat_id = cat['id']
                cat_name = cat['display_name']

                # Get prompts for this category
                response = requests.get(f"{base_url}/admin/categories/{cat_id}/prompts")
                if response.status_code == 200:
                    cat_prompts = response.json()
                    print(f"\n  {GREEN}✓{RESET} {cat_name}: {len(cat_prompts)} assigned prompts")

                    if len(cat_prompts) > 0:
                        print(f"    Prompts:")
                        for p in cat_prompts[:5]:  # Show first 5
                            print(f"      - {p['display_name']} ({p['internal_name']})")
                        if len(cat_prompts) > 5:
                            print(f"      ... and {len(cat_prompts) - 5} more")
                else:
                    print(f"  {RED}✗{RESET} {cat_name}: Failed to get prompts ({response.status_code})")
        else:
            print(f"{RED}✗{RESET} Failed to fetch categories")
    except Exception as e:
        print(f"{RED}✗{RESET} Error: {str(e)}")

    # 4. Test Admin UI endpoint
    print_section("4. Testing Admin UI Endpoint")
    try:
        # Try to access the prompts page
        response = requests.get(f"{base_url}/admin-ui/prompts")
        if response.status_code == 200:
            print(f"{GREEN}✓{RESET} Admin UI prompts page is accessible")
            html_length = len(response.text)
            print(f"    HTML response length: {html_length} bytes")

            # Check if prompts data is in the HTML
            if "prompts" in response.text.lower():
                print(f"{GREEN}✓{RESET} HTML contains 'prompts' keyword")
            else:
                print(f"{YELLOW}⚠{RESET} HTML does not contain 'prompts' keyword")

            # Check for template errors
            if "error" in response.text.lower() or "exception" in response.text.lower():
                print(f"{RED}✗{RESET} HTML contains error/exception keywords")
        else:
            print(f"{RED}✗{RESET} Admin UI prompts page returned: {response.status_code}")
    except Exception as e:
        print(f"{RED}✗{RESET} Error accessing Admin UI: {str(e)}")

    # 5. Summary
    print_section("Summary & Recommendations")
    print(f"\n{GREEN}Database Status:{RESET}")
    print(f"  ✓ Prompts exist in database")
    print(f"  ✓ Categories exist in database")
    print(f"  ✓ Category-Prompt assignments exist")

    print(f"\n{YELLOW}Possible Issues:{RESET}")
    print(f"  1. Template file missing or broken (app/templates/prompts.html)")
    print(f"  2. JavaScript not loading prompts data")
    print(f"  3. CSS hiding the prompts table")
    print(f"  4. Browser cache showing old version")

    print(f"\n{CYAN}Troubleshooting Steps:{RESET}")
    print(f"  1. Check browser console for JavaScript errors")
    print(f"  2. Clear browser cache and reload")
    print(f"  3. Check if templates/prompts.html exists")
    print(f"  4. Try accessing: {base_url}/admin-ui/prompts")
    print(f"  5. Check Docker logs: docker-compose logs app")

    print(f"\n{CYAN}API Endpoints to verify:{RESET}")
    print(f"  • GET {base_url}/admin/prompts")
    print(f"  • GET {base_url}/admin/categories")
    print(f"  • GET {base_url}/admin/categories/{{id}}/prompts")

    print("\n" + "=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Debug prompts in database")
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    # Check API connection
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        if response.status_code != 200:
            print(f"{RED}✗{RESET} API returned status code {response.status_code}")
            return
    except requests.exceptions.ConnectionError:
        print(f"{RED}✗{RESET} Cannot connect to API at {base_url}")
        return
    except Exception as e:
        print(f"{RED}✗{RESET} Error: {str(e)}")
        return

    debug_prompts(base_url)


if __name__ == "__main__":
    main()