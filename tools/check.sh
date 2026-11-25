#!/bin/sh
# Every check before a build that goes to the phone, in one go:
#   unit tests, Python 3.8 syntax, QML syntax, the D-Bus smoke test, stray and private files,
#   and with --rpm the RPM build. Prints one line per check and a summary; exits non-zero on failure.
#
# Linux, or from Windows:  wsl -d <distro> --cd <repo> -- sh tools/check.sh --rpm
# Needs python3 with dbus-python and pygobject, dbus-run-session, rpm-build, and qmllint
# (Fedora: qt5-qtdeclarative-devel).
cd "$(dirname "$0")/.." || exit 2
LOG=$(mktemp -d)
FAILED=""
# A Windows checkout seen from WSL belongs to another user, and git refuses it ("dubious ownership")
git() { command git -c safe.directory="$(pwd)" "$@"; }
git rev-parse --git-dir > /dev/null || { echo "git cannot read this checkout"; exit 2; }

run() {     # run <name> <command...>: output goes to $LOG/<name>.log, shown only on failure
    name=$1; shift
    if "$@" > "$LOG/$name.log" 2>&1; then
        printf '  ok    %s\n' "$name"
    else
        printf '  FAIL  %s\n' "$name"
        sed 's/^/        /' "$LOG/$name.log" | tail -25
        FAILED="$FAILED $name"
    fi
}

unit_tests() {
    python3 -m unittest discover -s tests > "$LOG/unit-full.log" 2>&1
    status=$?
    # The failing tests and their last traceback lines, then the summary
    grep -E -A12 '^(ERROR|FAIL):' "$LOG/unit-full.log" | grep -vE '^-+$' | tail -40
    tail -3 "$LOG/unit-full.log"
    return $status
}

py38() {
    python3 - <<'EOF'
import ast, glob, sys
files = glob.glob("daemon/**/*.py", recursive=True) + glob.glob("data/contact-names")
for f in files:
    ast.parse(open(f, encoding="utf-8").read(), f, feature_version=(3, 8))
print(len(files), "files parse as Python 3.8")
EOF
}

qml_lint() {
    lint=$(command -v qmllint-qt5 || command -v /usr/lib64/qt5/bin/qmllint || command -v qmllint) || {
        echo "qmllint not found (Fedora: dnf install qt5-qtdeclarative-devel)"; return 1; }
    # shellcheck disable=SC2046
    "$lint" $(find qml -name '*.qml' | sort) && echo "$(find qml -name '*.qml' | wc -l) QML files"
    # Qt 5.6 runs ES5 only: arrow functions and let/const break at runtime, not in qmllint
    # (comment lines are skipped: they may quote code in backticks)
    if grep -nE '=>|\blet |\bconst |`' $(find qml -name '*.qml') | grep -vE '^[^:]+:[0-9]+:[[:space:]]*//'; then
        echo "ES6 syntax found"; return 1
    fi
}

smoke() {
    dbus-run-session -- sh tools/smoke-daemon.sh "$(pwd)" > "$LOG/smoke-full.log" 2>&1
    status=$?
    grep -E -- '^--- |Traceback' "$LOG/smoke-full.log"
    grep -E -- '-> .*Error' "$LOG/smoke-full.log"
    return $status
}

stray_files() {
    # build-rpm.sh packs the working tree, untracked files included
    status=$(git status --porcelain --untracked-files=all) || return 1
    untracked=$(printf '%s\n' "$status" | grep '^??' | grep -v '^?? RPMS/')
    [ -z "$untracked" ] || { echo "Untracked files would end up in the RPM:"; echo "$untracked"; return 1; }
}

private_data() {
    # Nothing that identifies the user's phone or watch: LAN addresses, real Bluetooth addresses
    # (tests use AA:BB:CC:...), config files
    git ls-files > /dev/null || return 1
    hits=$(git grep -nE '192\.168\.[0-9]+\.[0-9]+|([0-9A-F]{2}:){5}[0-9A-F]{2}' -- . ':!*.md' |
           grep -vE 'AA:BB:CC:|00:00:00:00:00:00|FF:FF:FF:FF:FF:FF')
    git ls-files | grep -E '(^|/)config\.json$' && hits="$hits config.json tracked"
    [ -z "$hits" ] || { echo "$hits"; return 1; }
}

echo "Checks ($(git describe --tags --always --dirty 2>/dev/null))"
run unit-tests unit_tests
run python-3.8 py38
run qml qml_lint
run smoke-test smoke
run stray-files stray_files
run private-data private_data

if [ "${1:-}" = "--rpm" ] && [ -z "$FAILED" ]; then
    run rpm sh tools/build-rpm.sh
    rpm=$(ls -t RPMS/noarch/*.noarch.rpm 2>/dev/null | head -1)
    [ -n "$rpm" ] && printf '        %s (%s bytes)\n' "$rpm" "$(wc -c < "$rpm")"
fi

if [ -n "$FAILED" ]; then
    echo "FAILED:$FAILED   (logs in $LOG)"
    exit 1
fi
echo "All checks passed."
rm -rf "$LOG"
