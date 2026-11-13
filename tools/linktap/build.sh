#!/bin/sh
# Builds the linktap helper: fetches the Ableton Link SDK (GPL-2.0-or-later) next to
# this script on first use, then compiles. Needs git and a C++17 compiler.
set -e
cd "$(dirname "$0")"
LINK="${LINK_SDK:-link}"
if [ ! -f "$LINK/include/ableton/LinkAudio.hpp" ]; then
  git clone --depth 1 --recurse-submodules --shallow-submodules https://github.com/Ableton/link.git "$LINK"
fi
case "$(uname)" in
  Darwin) PLATFORM="-DLINK_PLATFORM_MACOSX=1"; LIBS="" ;;
  *)      PLATFORM="-DLINK_PLATFORM_LINUX=1";  LIBS="-pthread -latomic" ;;
esac
"${CXX:-c++}" -std=c++17 -O2 $PLATFORM -DLINK_PLATFORM_UNIX=1 \
  -I"$LINK/include" -I"$LINK/modules/asio-standalone/asio/include" \
  -Wno-multichar main.cpp -o linktap $LIBS
echo "built $(pwd)/linktap"
