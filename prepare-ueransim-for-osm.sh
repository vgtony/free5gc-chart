#!/usr/bin/env bash
set -Eeuo pipefail

NAMESPACE=""
REGISTRY="10.160.101.91:32000"
IMAGE_TAG="3.3.0"
SECRET_NAME="ueransim-ue-auth"
BUILDER_IMAGE="ghcr.io/osscontainertools/kaniko:v1.28.2"
BUILD_CONTEXT="git://github.com/vgtony/free5gc-chart.git#refs/heads/ueransim-free5gc#7838df9eda46fe39ce9352f5491278abd2ecc578"
SKIP_BUILD=false
FORCE_BUILD=false
SKIP_SECRET=false

usage() {
  printf '%s\n' \
    "Usage: $0 --namespace NAMESPACE [options]" "" \
    "Publishes the UERANSIM image if missing and creates the UE Secret." "" \
    "  -n, --namespace NAME     Target namespace (required)" \
    "      --registry HOST:PORT Registry reachable by every worker" \
    "      --image-tag TAG      Image tag (default: 3.3.0)" \
    "      --secret-name NAME   Secret name (default: ueransim-ue-auth)" \
    "      --force-build        Rebuild even if the image exists" \
    "      --skip-build         Skip image checking and building" \
    "      --skip-secret        Skip Secret creation" \
    "  -h, --help               Show this help" "" \
    "For unattended use, set UERANSIM_UE_KEY and UERANSIM_UE_OP." \
    "Do not put subscriber credentials on the command line."
}
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    -n|--namespace) (($# >= 2)) || die "$1 requires a value"; NAMESPACE=$2; shift 2 ;;
    --registry) (($# >= 2)) || die "$1 requires a value"; REGISTRY=$2; shift 2 ;;
    --image-tag) (($# >= 2)) || die "$1 requires a value"; IMAGE_TAG=$2; shift 2 ;;
    --secret-name) (($# >= 2)) || die "$1 requires a value"; SECRET_NAME=$2; shift 2 ;;
    --force-build) FORCE_BUILD=true; shift ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --skip-secret) SKIP_SECRET=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ -n "$NAMESPACE" ]] || { usage >&2; die "--namespace is required"; }
[[ "$NAMESPACE" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || die "invalid namespace"
[[ "$SECRET_NAME" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]] || die "invalid Secret name"
[[ "$IMAGE_TAG" =~ ^[A-Za-z0-9_.-]+$ ]] || die "invalid image tag"
[[ "$REGISTRY" =~ ^[A-Za-z0-9._-]+:[0-9]+$ ]] || die "registry must be HOST:PORT"
command -v kubectl >/dev/null || die "kubectl is required"
kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 ||
  die "namespace '$NAMESPACE' does not exist; create it or let OSM create it first"

image_exists() {
  command -v curl >/dev/null || return 1
  local response
  response=$(curl --connect-timeout 5 --max-time 15 -fsS \
    "http://${REGISTRY}/v2/ueransim/tags/list") || return 1
  grep -Fq "\"${IMAGE_TAG}\"" <<<"$response"
}

if [[ "$SKIP_BUILD" == false ]]; then
  if [[ "$FORCE_BUILD" == false ]] && image_exists; then
    printf 'Image already available: %s/ueransim:%s\n' "$REGISTRY" "$IMAGE_TAG"
  else
    job_name="build-ueransim-${IMAGE_TAG//[^A-Za-z0-9]/-}"
    job_name=${job_name,,}
    printf 'Building %s/ueransim:%s inside Kubernetes...\n' "$REGISTRY" "$IMAGE_TAG"
    if kubectl -n "$NAMESPACE" get job "$job_name" >/dev/null 2>&1; then
      kubectl -n "$NAMESPACE" delete job "$job_name" --wait=true
    fi
    kubectl -n "$NAMESPACE" create job "$job_name" --image="$BUILDER_IMAGE" -- \
      /kaniko/executor "--context=${BUILD_CONTEXT}" \
      --dockerfile=images/ueransim/Dockerfile \
      "--destination=${REGISTRY}/ueransim:${IMAGE_TAG}" \
      "--insecure-registry=${REGISTRY}" --digest-file=/dev/termination-log --cache=false
    if ! kubectl -n "$NAMESPACE" wait --for=condition=Ready pod \
      -l "job-name=${job_name}" --timeout=3m; then
      kubectl -n "$NAMESPACE" describe job "$job_name" >&2
      die "builder pod did not become ready; job '$job_name' was retained"
    fi
    kubectl -n "$NAMESPACE" logs -f "job/${job_name}"
    succeeded=$(kubectl -n "$NAMESPACE" get job "$job_name" \
      -o jsonpath='{.status.succeeded}')
    [[ "$succeeded" == "1" ]] ||
      die "image build failed; job '$job_name' was retained for diagnosis"
    kubectl -n "$NAMESPACE" delete job "$job_name" --wait=true
    image_exists || die "build completed but the registry does not report the tag"
    printf 'Published image: %s/ueransim:%s\n' "$REGISTRY" "$IMAGE_TAG"
  fi
fi

if [[ "$SKIP_SECRET" == false ]]; then
  if [[ -z "${UERANSIM_UE_KEY:-}" ]]; then
    [[ -r /dev/tty ]] || die "set UERANSIM_UE_KEY for unattended use"
    read -r -s -p 'UE permanent key (32 hex characters): ' UERANSIM_UE_KEY </dev/tty
    printf '\n' >/dev/tty
  fi
  if [[ -z "${UERANSIM_UE_OP:-}" ]]; then
    [[ -r /dev/tty ]] || die "set UERANSIM_UE_OP for unattended use"
    read -r -s -p 'UE OPc (32 hex characters): ' UERANSIM_UE_OP </dev/tty
    printf '\n' >/dev/tty
  fi
  [[ "$UERANSIM_UE_KEY" =~ ^[[:xdigit:]]{32}$ ]] ||
    die "UE key must contain exactly 32 hexadecimal characters"
  [[ "$UERANSIM_UE_OP" =~ ^[[:xdigit:]]{32}$ ]] ||
    die "UE OPc must contain exactly 32 hexadecimal characters"
  kubectl -n "$NAMESPACE" create secret generic "$SECRET_NAME" \
    --from-literal="key=${UERANSIM_UE_KEY}" --from-literal="op=${UERANSIM_UE_OP}" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  unset UERANSIM_UE_KEY UERANSIM_UE_OP
  printf 'Created or updated Secret: %s/%s\n' "$NAMESPACE" "$SECRET_NAME"
fi

printf '\nPreparation complete. OSM can install the chart in namespace %s.\n' "$NAMESPACE"
