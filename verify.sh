#!/bin/sh
# qtdf verification entry point — the ONE command to check this repo.
# Runs every test suite, verifies store hashes (if a store is present), and
# runs the end-to-end demo. Prints PASS/FAIL per step and exits nonzero on
# any failure. Needs only Python 3.10+; no dependencies, no network.
set -u
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
fail=0

step() {  # step <name> <cmd...>
    name=$1; shift
    if out=$("$@" 2>&1); then
        echo "PASS  $name  $(printf '%s' "$out" | tail -1)"
    else
        fail=1
        echo "FAIL  $name"
        printf '%s\n' "$out" | tail -15
    fi
}

echo "qtdf verify — $($PY --version 2>&1) on $(uname -sm)"
echo "----------------------------------------------------------"
for t in tests/test_*.py; do
    step "$(basename "$t" .py)" "$PY" "$t"
done
if [ -d store ]; then
    step "store-hash-verification" "$PY" -m qtdf.cli verify store
fi
step "end-to-end-demo" "$PY" -m qtdf.cli demo --rows 6 --cols 6
echo "----------------------------------------------------------"
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "CHECKS FAILED — see above"
fi
exit $fail
