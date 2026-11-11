#!/bin/sh
# Double-click to start ElfJamAlong with the settings in elfjamalong.toml.
cd "$(dirname "$0")" || exit 1
[ -x tools/livetap/livetap ] || tools/livetap/build.sh
exec uv run elfjamalong run "$@"
