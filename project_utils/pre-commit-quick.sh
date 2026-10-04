#!/usr/bin/env bash
set -euo pipefail

chmod +x ./project_utils/run_autofix.sh
chmod +x ./project_utils/run_tests.sh
echo "Local CI: Running code quality checks before pushing..."
echo ""
./project_utils/run_autofix.sh
FORMATTERS_EXIT=$?
./project_utils/run_tests.sh
TESTS_EXIT=$?
echo ""
echo "========================================================"
echo "  LOCAL CI - AGGREGATE SUMMARY"
echo "========================================================"
echo ""
TOTAL_FAILURES=0
if [ $FORMATTERS_EXIT -ne 0 ]; then
	echo "  ✗ run_autofix.sh exited with code $FORMATTERS_EXIT"
	TOTAL_FAILURES=$((TOTAL_FAILURES + 1))
else
	echo "  ✓ run_autofix.sh completed (see above for details)"
fi
if [ $TESTS_EXIT -ne 0 ]; then
	echo "  ✗ run_tests.sh exited with code $TESTS_EXIT"
	TOTAL_FAILURES=$((TOTAL_FAILURES + 1))
else
	echo "  ✓ run_tests.sh completed (see above for details)"
fi
echo ""
echo "========================================================"
if [ $TOTAL_FAILURES -eq 0 ]; then
	echo "  All checks passed! Proceeding with git push..."
	echo "========================================================"
	exit 0
else
	echo "  ⚠  $TOTAL_FAILURES script(s) reported issues."
	echo "  Review the output above for details."
	echo ""
	echo "  You can fix the issues and try again, or push anyway."
	echo "========================================================"
	exit 0
fi
