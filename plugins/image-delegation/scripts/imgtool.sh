#!/bin/sh
# IMGTOOL entry point: sh imgtool.sh <subcommand> [args]  (text output only)
exec sh "$(cd "$(dirname "$0")" && pwd)/py.sh" imgtool.py "$@"
