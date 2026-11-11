#!/bin/sh
# Double-click to start JamAlong with the settings in jamalong.toml.
cd "$(dirname "$0")" || exit 1
[ -x tools/livetap/livetap ] || tools/livetap/build.sh
exec uv run jamalong run "$@"
