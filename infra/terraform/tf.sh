#!/usr/bin/env bash
# Runs Terraform in Docker, so the only local requirement is Docker. (On this Windows
# machine, Application Control blocks the native OCI provider plugin.)
#
#   ./tf.sh init
#   ./tf.sh plan
#   ./tf.sh apply -var availability_domain=1
#
# Keys are mounted read-only. OCI_KEY and SSH_PUB override their default locations.
set -euo pipefail
cd "$(dirname "$0")"

OCI_KEY="${OCI_KEY:-$HOME/.oci/oci_api_key.pem}"
SSH_PUB="${SSH_PUB:-$HOME/.ssh/ghostbus.pub}"

# Docker Desktop on Windows needs C:/... paths, not Git Bash's /c/...
winpath() { if command -v cygpath >/dev/null; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

# The container sees the keys at fixed paths, so point the variables there. Applying a
# saved plan file takes no -var flags.
vars=()
case "${1:-}" in
  plan | apply | destroy | refresh | import | console)
    last="${*: -1}"
    if [[ "$1" != apply || ! -f "$last" ]]; then
      vars=(-var private_key_path=/keys/oci_api_key.pem -var ssh_public_key_path=/keys/ssh.pub)
    fi
    ;;
esac

tty=()
[[ -t 0 && -t 1 ]] && tty=(-it)

MSYS_NO_PATHCONV=1 exec docker run --rm "${tty[@]}" \
  -v "$(winpath "$PWD"):/work" -w /work \
  -v "$(winpath "$OCI_KEY"):/keys/oci_api_key.pem:ro" \
  -v "$(winpath "$SSH_PUB"):/keys/ssh.pub:ro" \
  hashicorp/terraform:1.17.2 "$@" "${vars[@]}"
