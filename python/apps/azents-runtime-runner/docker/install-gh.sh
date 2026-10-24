#!/bin/sh
# Install the same GitHub CLI release as the last successful Runner image.
set -eu

architecture="$1"
prefix="$2"
version=2.103.1
case "$architecture" in
    amd64) checksum=57500f347b5e84efb6578c9b644eeb3b4e54046762635a939dd0ee2cca1c1add ;;
    arm64) checksum=25b1287471a73a3cca32e5d2d2798ae26abea0243db1b9e4a8c1be506fad1bfe ;;
    *) echo "Unsupported GitHub CLI architecture: $architecture" >&2; exit 1 ;;
esac

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
archive="gh_${version}_linux_${architecture}.tar.gz"
curl -fsSL "https://github.com/cli/cli/releases/download/v${version}/${archive}" \
    -o "$scratch/gh.tar.gz"
echo "$checksum  $scratch/gh.tar.gz" | sha256sum --check --status
# Extract only the executable after authenticating the complete archive.
tar -xzf "$scratch/gh.tar.gz" -C "$scratch" \
    "gh_${version}_linux_${architecture}/bin/gh"
install -d "$prefix/bin"
install -m 755 "$scratch/gh_${version}_linux_${architecture}/bin/gh" "$prefix/bin/gh"
