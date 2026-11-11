#!/bin/sh
# Builds the livetap helper (needs Xcode command line tools, macOS 14.4+).
cd "$(dirname "$0")" && xcrun swiftc -O -swift-version 5 main.swift -o livetap \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
