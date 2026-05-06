"""Run regression checks for hooks/validate_json.py."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path


sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_json  # noqa: E402


TESTDATA_DIR = Path(__file__).resolve().parent / "testdata"


def run_case(args: list[str]) -> tuple[int, str, str]:
    """Run the validator and capture stdout/stderr.

    Args:
        args: Arguments passed to validate_json.main().

    Returns:
        Exit code, stdout text, and stderr text.
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = validate_json.main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def require(condition: bool, message: str) -> None:
    """Raise an assertion error when a test expectation fails.

    Args:
        condition: Test condition.
        message: Failure message.
    """
    if not condition:
        raise AssertionError(message)


def test_valid_single_file() -> None:
    """Validate one passing knowledge article."""
    exit_code, stdout, stderr = run_case([str(TESTDATA_DIR / "valid_full.json")])

    require(exit_code == 0, "valid_full.json should pass")
    require("passed=1, failed=0" in stdout, "valid summary should be printed")
    require("[INFO] Starting JSON validation" in stderr, "valid run should log start")


def test_valid_glob() -> None:
    """Validate wildcard expansion for multiple passing files."""
    pattern = str(TESTDATA_DIR / "valid_*.json")
    exit_code, stdout, stderr = run_case([pattern])

    require(exit_code == 0, "valid glob should pass")
    require("total=2, passed=2, failed=0" in stdout, "glob summary mismatch")
    require("Expanded glob" in stderr, "valid glob should log expansion")


def test_invalid_files() -> None:
    """Validate expected failures across bad fixtures."""
    pattern = str(TESTDATA_DIR / "invalid_*.json")
    exit_code, stdout, stderr = run_case([pattern])

    require(exit_code == 1, "invalid glob should fail")
    require(stdout == "", "invalid run should not write stdout")
    require("Invalid JSON" in stderr, "JSON parse error was not reported")
    require("Missing required field: source_url" in stderr, "missing field missed")
    require("Top-level JSON value must be an object" in stderr, "top-level missed")
    require("Field id must be str" in stderr, "type error missed")
    require("Field status must be one of" in stderr, "status error missed")
    require("Field score must be between 1 and 10" in stderr, "score error missed")
    require("total=5, passed=0, failed=5" in stderr, "invalid summary mismatch")


def test_mixed_files() -> None:
    """Validate mixed pass/fail input returns failure and full summary."""
    args = [
        str(TESTDATA_DIR / "valid_minimal.json"),
        str(TESTDATA_DIR / "invalid_bad_values.json"),
    ]
    exit_code, stdout, stderr = run_case(args)

    require(exit_code == 1, "mixed run should fail")
    require(stdout == "", "mixed failure should not write stdout")
    require("OK:" in stderr, "mixed output should include passing file")
    require("FAIL:" in stderr, "mixed output should include failing file")
    require("total=2, passed=1, failed=1" in stderr, "mixed summary mismatch")


def main() -> int:
    """Run all regression tests.

    Returns:
        Process exit code: 0 for success, 1 for failure.
    """
    tests = [
        test_valid_single_file,
        test_valid_glob,
        test_invalid_files,
        test_mixed_files,
    ]

    failures: list[str] = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")

    if failures:
        sys.stderr.write("Validation hook tests failed:\n")
        for failure in failures:
            sys.stderr.write(f"  - {failure}\n")
        return 1

    sys.stdout.write(f"Validation hook tests passed: {len(tests)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
