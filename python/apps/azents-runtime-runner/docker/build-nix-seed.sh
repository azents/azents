#!/bin/sh
set -eu

NIX_VERSION="${NIX_VERSION:?NIX_VERSION is required}"
NIXPKGS_REVISION="${NIXPKGS_REVISION:?NIXPKGS_REVISION is required}"
SEED_GENERATION="${SEED_GENERATION:?SEED_GENERATION is required}"
SEED_ROOT="${1:-/opt/azents/nix-seed}"
TRUSTED_PUBLIC_KEY="cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
NIX_FLAGS="--extra-experimental-features nix-command --extra-experimental-features flakes"

if [ "$(nix --version)" != "nix (Nix) ${NIX_VERSION}" ]; then
    echo "Unexpected Nix version in seed image." >&2
    exit 1
fi

release_profile="$(readlink -f /root/.nix-profile)"
if [ ! -x "${release_profile}/bin/nix" ] || [ ! -x "${release_profile}/bin/nix-store" ]; then
    echo "Nix release profile is incomplete." >&2
    exit 1
fi

archive_json="$(
    nix ${NIX_FLAGS} flake archive --json \
        "github:NixOS/nixpkgs/${NIXPKGS_REVISION}"
)"
catalog_store_path="${archive_json#*\"path\":\"}"
catalog_store_path="${catalog_store_path%%\"*}"
case "${catalog_store_path}" in
    /nix/store/*-source) ;;
    *)
        echo "Pinned Nixpkgs archive did not resolve to one store source." >&2
        exit 1
        ;;
esac

rm -rf "${SEED_ROOT}" /tmp/azents-nix-seed-root
mkdir -p "${SEED_ROOT}" /tmp/azents-nix-seed-root

nix ${NIX_FLAGS} registry add \
    --registry "${SEED_ROOT}/registry.json" \
    nixpkgs \
    "path:${catalog_store_path}"

cat > "${SEED_ROOT}/nix.conf" <<EOF
experimental-features = nix-command flakes
flake-registry = /nix/var/azents/registry.json
substituters = https://cache.nixos.org/
trusted-public-keys = ${TRUSTED_PUBLIC_KEY}
require-sigs = true
fallback = false
builders =
max-jobs = 0
min-free = 1073741824
max-free = 2147483648
keep-derivations = false
keep-outputs = false
EOF

nix ${NIX_FLAGS} copy \
    --no-check-sigs \
    --to "local?root=/tmp/azents-nix-seed-root" \
    "${release_profile}" \
    "${catalog_store_path}"

seed_nix_root="/tmp/azents-nix-seed-root/nix"
mkdir -p \
    "${seed_nix_root}/etc/nix" \
    "${seed_nix_root}/var/azents" \
    "${seed_nix_root}/var/nix/gcroots/azents" \
    "${seed_nix_root}/var/nix/profiles"
cp "${SEED_ROOT}/nix.conf" "${seed_nix_root}/etc/nix/nix.conf"
cp "${SEED_ROOT}/registry.json" "${seed_nix_root}/var/azents/registry.json"
ln -s "${release_profile}" \
    "${seed_nix_root}/var/nix/profiles/azents-release"
ln -s "${catalog_store_path}" \
    "${seed_nix_root}/var/nix/gcroots/azents/nixpkgs"
rm -f \
    "${seed_nix_root}/var/nix/db/db.sqlite-shm" \
    "${seed_nix_root}/var/nix/db/db.sqlite-wal"

tar \
    --sort=name \
    --mtime="@0" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C "${seed_nix_root}" \
    -czf "${SEED_ROOT}/empty-store.tar.gz" \
    etc \
    store \
    var

nix-store -qR "${release_profile}" "${catalog_store_path}" \
    | sort \
    | xargs nix-store --export \
    | gzip -9n \
    > "${SEED_ROOT}/release-export.nar.gz"

empty_store_sha256="$(
    sha256sum "${SEED_ROOT}/empty-store.tar.gz" | cut -d ' ' -f 1
)"
release_export_sha256="$(
    sha256sum "${SEED_ROOT}/release-export.nar.gz" | cut -d ' ' -f 1
)"
registry_sha256="$(
    sha256sum "${SEED_ROOT}/registry.json" | cut -d ' ' -f 1
)"
nix_conf_sha256="$(
    sha256sum "${SEED_ROOT}/nix.conf" | cut -d ' ' -f 1
)"

cat > "${SEED_ROOT}/manifest.json" <<EOF
{
  "schema_version": 1,
  "generation": "${SEED_GENERATION}",
  "nix_version": "${NIX_VERSION}",
  "nixpkgs_revision": "${NIXPKGS_REVISION}",
  "release_profile_store_path": "${release_profile}",
  "catalog_store_path": "${catalog_store_path}",
  "artifacts": {
    "empty_store": {
      "path": "empty-store.tar.gz",
      "sha256": "${empty_store_sha256}"
    },
    "release_export": {
      "path": "release-export.nar.gz",
      "sha256": "${release_export_sha256}"
    },
    "registry": {
      "path": "registry.json",
      "sha256": "${registry_sha256}"
    },
    "nix_conf": {
      "path": "nix.conf",
      "sha256": "${nix_conf_sha256}"
    }
  }
}
EOF

chmod -R a-w "${SEED_ROOT}"
