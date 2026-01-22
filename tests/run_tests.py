#!/usr/bin/env python3
"""Main test runner for A2A Gateway tests.

Usage:
    # Run all tests (unit + integration)
    python -m tests.run_tests --prefix $PREFIX

    # Run only unit tests (no external services needed)
    python -m tests.run_tests --unit

    # Run only integration tests
    python -m tests.run_tests --integration --prefix $PREFIX

    # Run specific test
    python -m tests.run_tests -k test_addition_2_plus_2

    # Run with verbose output
    python -m tests.run_tests -v
"""

import argparse
import os
import subprocess
import sys
import json


def get_app_url(app_name: str) -> str:
    """Get app URL from Databricks CLI."""
    try:
        result = subprocess.run(
            ["databricks", "apps", "get", app_name, "--output", "json"],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return data.get("url", "")
    except Exception as e:
        print(f"Warning: Could not get URL for {app_name}: {e}")
        return ""


def main():
    parser = argparse.ArgumentParser(description="Run A2A Gateway tests")
    parser.add_argument("--gateway-url", help="Gateway URL (or set GATEWAY_URL env)")
    parser.add_argument("--echo-agent-url", help="Echo Agent URL (or set ECHO_AGENT_URL env)")
    parser.add_argument("--calculator-agent-url", help="Calculator Agent URL (or set CALCULATOR_AGENT_URL env)")
    parser.add_argument("--databricks-host", help="Databricks host (or set DATABRICKS_HOST env)")
    parser.add_argument("--prefix", default="marcin", help="Resource prefix (default: marcin)")
    parser.add_argument("-k", "--filter", help="pytest -k filter expression")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--collect-only", action="store_true", help="Only collect tests, don't run")
    parser.add_argument("--unit", action="store_true", help="Run only unit tests")
    parser.add_argument("--integration", action="store_true", help="Run only integration tests")

    args = parser.parse_args()

    # Determine test path
    if args.unit:
        test_path = "tests/unit/"
    elif args.integration:
        test_path = "tests/integration/"
    else:
        test_path = "tests/"

    # Build pytest command
    pytest_args = [sys.executable, "-m", "pytest", test_path]

    # Get URLs for tests that need them
    prefix = args.prefix or os.environ.get("PREFIX", "marcin")

    gateway_url = args.gateway_url or os.environ.get("GATEWAY_URL")
    if not gateway_url:
        gateway_url = get_app_url(f"{prefix}-a2a-gateway")

    echo_url = args.echo_agent_url or os.environ.get("ECHO_AGENT_URL")
    if not echo_url:
        echo_url = get_app_url(f"{prefix}-echo-agent")

    calc_url = args.calculator_agent_url or os.environ.get("CALCULATOR_AGENT_URL")
    if not calc_url:
        calc_url = get_app_url(f"{prefix}-calculator-agent")

    if gateway_url:
        pytest_args.append(f"--gateway-url={gateway_url}")
    if echo_url:
        pytest_args.append(f"--echo-agent-url={echo_url}")
    if calc_url:
        pytest_args.append(f"--calculator-agent-url={calc_url}")
    pytest_args.append(f"--prefix={prefix}")

    if args.databricks_host:
        pytest_args.append(f"--databricks-host={args.databricks_host}")

    print(f"Gateway URL: {gateway_url}")
    print(f"Echo Agent URL: {echo_url}")
    print(f"Calculator Agent URL: {calc_url}")
    print(f"Prefix: {prefix}")

    if args.filter:
        pytest_args.extend(["-k", args.filter])

    if args.verbose:
        pytest_args.append("-v")

    if args.collect_only:
        pytest_args.append("--collect-only")

    print(f"Running: {' '.join(pytest_args)}")
    print("-" * 60)

    # Run pytest
    result = subprocess.run(pytest_args)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
