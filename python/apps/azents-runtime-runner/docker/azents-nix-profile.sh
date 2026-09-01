#!/bin/sh

azents_nix_path="/nix/var/state/azents-agent/profiles/profile/bin:/nix/var/nix/profiles/azents-release/bin"
case ":${PATH}:" in
    *":/nix/var/state/azents-agent/profiles/profile/bin:"*) ;;
    *) PATH="${azents_nix_path}:${PATH}" ;;
esac
export PATH
