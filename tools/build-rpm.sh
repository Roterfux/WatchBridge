#!/bin/sh
# Build the noarch RPM with plain rpmbuild (no Sailfish SDK needed).
# Usage: tools/build-rpm.sh   -> RPMS/noarch/harbour-watchbridge-*.rpm
set -e
cd "$(dirname "$0")/.."
SRC=$(pwd)
NAME=harbour-watchbridge
VERSION=$(sed -n 's/^Version:[[:space:]]*//p' rpm/$NAME.spec)
TOP=$(mktemp -d)
trap 'rm -rf "$TOP"' EXIT

mkdir -p "$TOP/SOURCES" "$TOP/stage/$NAME-$VERSION"
tar -C "$SRC" --exclude=__pycache__ --exclude=RPMS --exclude=.git \
    -cf - . | tar -C "$TOP/stage/$NAME-$VERSION" -xf -
tar -C "$TOP/stage" -cjf "$TOP/SOURCES/$NAME-$VERSION.tar.bz2" "$NAME-$VERSION"

rpmbuild --define "_topdir $TOP" --define "_rpmdir $SRC/RPMS" -bb rpm/$NAME.spec
ls -l "$SRC"/RPMS/noarch/
