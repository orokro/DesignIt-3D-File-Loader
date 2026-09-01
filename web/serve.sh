#!/bin/sh
# The viewer fetches binaries with fetch(), so it needs a server -- file:// will
# not work. Serve the repository root so /web and /data are both reachable.
cd "$(dirname "$0")/.." || exit 1
echo "http://localhost:8080/web/"
exec python3 -m http.server 8080
