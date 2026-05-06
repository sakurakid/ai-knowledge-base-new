"""Run regression checks for hooks/check_quality.py."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path


sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_quality  # noqa: E402


TESTDATA_DIR = Path(__file__).resolve().parent / "testdata"


def run_case(args: list[str]) -> tuple[int, str, str]:
    """Run the quality checker and capture output.

    Args:
        args: Arguments passed to check_quality.main().

    Returns:
        Exit code, stdout text, and stderr text.
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = check_quality.main(args)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def require(condition: bool, message: str) -> None:
    """Raise an assertion error when a test expectation fails.

    Args:
        condition: Test condition.
        message: Failure message.
    """
    if not condition:
        raise AssertionError(message)


def test_grade_a_file() -> None:
    """Verify a high-quality file passes with grade A."""
    exit_code, stdout, stderr = run_case([str(TESTDATA_DIR / "quality_a.json")])

    require(exit_code == 0, "quality_a.json should pass")
    require("Grade: A" in stdout, "A grade should be printed")
    require("Summary: total=1, A=1, B=0, C=0" in stdout, "A summary mismatch")
    require("[INFO] Starting quality check" in stderr, "A run should log start")


def test_grade_c_file() -> None:
    """Verify a low-quality file fails with grade C."""
    exit_code, stdout, stderr = run_case([str(TESTDATA_DIR / "quality_c.json")])

    require(exit_code == 1, "quality_c.json should fail")
    require(stdout == "", "C run should not write stdout")
    require("Grade: C" in stderr, "C grade should be printed")
    require("hollow words" in stderr, "hollow-word reason should be printed")


def test_quality_glob() -> None:
    """Verify wildcard input scores multiple files."""
    pattern = str(TESTDATA_DIR / "quality_*.json")
    exit_code, stdout, stderr = run_case([pattern])

    require(exit_code == 1, "glob should fail because it includes C")
    require(stdout == "", "failing glob should not write stdout")
    require("Summary: total=2, A=1, B=0, C=1" in stderr, "glob summary mismatch")


def test_invalid_json_is_grade_c() -> None:
    """Verify unreadable JSON is treated as grade C."""
    exit_code, stdout, stderr = run_case([str(TESTDATA_DIR / "invalid_json.json")])

    require(exit_code == 1, "invalid JSON should fail")
    require(stdout == "", "invalid JSON should not write stdout")
    require("Invalid JSON" in stderr, "parse error should be printed")
    require("Grade: C" in stderr, "invalid JSON should be grade C")


def main() -> int:
    """Run all regression tests.

    Returns:
        Process exit code: 0 for success, 1 for failure.
    """
    tests = [
        test_grade_a_file,
        test_grade_c_file,
        test_quality_glob,
        test_invalid_json_is_grade_c,
    ]

    failures: list[str] = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")

    if failures:
        sys.stderr.write("Quality hook tests failed:\n")
        for failure in failures:
            sys.stderr.write(f"  - {failure}\n")
        return 1

    sys.stdout.write(f"Quality hook tests passed: {len(tests)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
