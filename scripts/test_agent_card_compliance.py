#!/usr/bin/env python3
"""
Test agent card A2A compliance.

Validates that generated agent cards conform to the A2A Protocol Specification:
https://a2a-protocol.org/latest/specification/

Usage:
    # Test with mock data (no Databricks connection needed)
    python test_agent_card_compliance.py --mock

    # Test with real UC connection
    python test_agent_card_compliance.py --name echo
"""

import argparse
import json
import sys


def validate_a2a_agent_card(card: dict) -> tuple[bool, list[str]]:
    """
    Validate agent card against A2A Protocol specification.

    Returns:
        (is_valid, list of errors/warnings)
    """
    errors = []
    warnings = []

    # === REQUIRED FIELDS (A2A spec section 4.4) ===
    if "name" not in card:
        errors.append("REQUIRED: 'name' field missing")
    elif not isinstance(card["name"], str) or not card["name"]:
        errors.append("REQUIRED: 'name' must be non-empty string")

    if "url" not in card:
        errors.append("REQUIRED: 'url' field missing")
    elif not isinstance(card["url"], str) or not card["url"]:
        errors.append("REQUIRED: 'url' must be non-empty string")
    elif not (card["url"].startswith("http") or card["url"].startswith("/")):
        warnings.append("WARNING: 'url' should be absolute URL or relative path")

    # === RECOMMENDED FIELDS ===
    if "description" not in card:
        warnings.append("RECOMMENDED: 'description' field missing")

    if "version" not in card:
        warnings.append("RECOMMENDED: 'version' field missing")

    # === SECURITY SCHEMES (A2A spec section 4.5) ===
    if "securitySchemes" not in card:
        errors.append("REQUIRED: 'securitySchemes' field missing for authenticated agents")
    else:
        schemes = card["securitySchemes"]
        if not isinstance(schemes, dict):
            errors.append("INVALID: 'securitySchemes' must be object")
        else:
            for name, scheme in schemes.items():
                if "type" not in scheme:
                    errors.append(f"REQUIRED: securitySchemes.{name}.type missing")
                elif scheme["type"] == "http":
                    if "scheme" not in scheme:
                        errors.append(f"REQUIRED: securitySchemes.{name}.scheme missing for HTTP auth")
                    elif scheme["scheme"] == "bearer":
                        if "bearerFormat" not in scheme:
                            warnings.append(f"RECOMMENDED: securitySchemes.{name}.bearerFormat missing")

    # === SECURITY REQUIREMENTS ===
    if "security" not in card:
        warnings.append("RECOMMENDED: 'security' requirements array missing")
    else:
        if not isinstance(card["security"], list):
            errors.append("INVALID: 'security' must be array")
        elif len(card["security"]) == 0:
            warnings.append("WARNING: 'security' array is empty")
        else:
            for i, req in enumerate(card["security"]):
                if not isinstance(req, dict):
                    errors.append(f"INVALID: security[{i}] must be object")

    # === CAPABILITIES ===
    if "capabilities" in card:
        caps = card["capabilities"]
        if not isinstance(caps, dict):
            errors.append("INVALID: 'capabilities' must be object")
        else:
            if "streaming" in caps and not isinstance(caps["streaming"], bool):
                errors.append("INVALID: capabilities.streaming must be boolean")
            if "pushNotifications" in caps and not isinstance(caps["pushNotifications"], bool):
                errors.append("INVALID: capabilities.pushNotifications must be boolean")

    # === INPUT/OUTPUT MODES ===
    for mode_field in ["defaultInputModes", "defaultOutputModes"]:
        if mode_field in card:
            if not isinstance(card[mode_field], list):
                errors.append(f"INVALID: '{mode_field}' must be array")
            elif not all(isinstance(m, str) for m in card[mode_field]):
                errors.append(f"INVALID: '{mode_field}' must contain strings")

    is_valid = len(errors) == 0
    return is_valid, errors + warnings


def create_mock_card() -> dict:
    """Create a mock agent card for testing without Databricks."""
    return {
        "name": "test-agent",
        "url": "https://test-agent.example.com/a2a",
        "description": "Test agent for compliance validation",
        "version": "1.0.0",
        "provider": {
            "organization": "Test Org"
        },
        "securitySchemes": {
            "bearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Bearer token authentication"
            }
        },
        "security": [
            {"bearer": []}
        ],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False
        },
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"]
    }


def main():
    parser = argparse.ArgumentParser(description="Test agent card A2A compliance")
    parser.add_argument("--name", "-n", help="Agent name (requires Databricks connection)")
    parser.add_argument("--mock", action="store_true", help="Use mock data instead of real UC")
    parser.add_argument("--json", "-j", help="Test card from JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show card contents")

    args = parser.parse_args()

    # Get the card to test
    if args.json:
        with open(args.json) as f:
            card = json.load(f)
        print(f"Testing card from: {args.json}")
    elif args.mock:
        card = create_mock_card()
        print("Testing mock agent card")
    elif args.name:
        from generate_agent_card import generate_agent_card
        card = generate_agent_card(args.name)
        print(f"Testing card for agent: {args.name}")
    else:
        print("Error: Specify --name, --mock, or --json", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print("\n--- Agent Card ---")
        print(json.dumps(card, indent=2))
        print("------------------\n")

    # Validate
    is_valid, messages = validate_a2a_agent_card(card)

    print(f"\n{'✓ VALID' if is_valid else '✗ INVALID'} A2A Agent Card\n")

    if messages:
        for msg in messages:
            prefix = "  ✗" if msg.startswith("REQUIRED") or msg.startswith("INVALID") else "  ⚠"
            print(f"{prefix} {msg}")

    print()

    # Summary
    errors = [m for m in messages if m.startswith("REQUIRED") or m.startswith("INVALID")]
    warnings = [m for m in messages if m.startswith("RECOMMENDED") or m.startswith("WARNING")]

    print(f"Errors: {len(errors)}, Warnings: {len(warnings)}")

    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
