#!/bin/bash

set -euo pipefail

test_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
chart_dir="$(cd -- "${test_dir}/../.." && pwd)"
example_dir="${chart_dir}/examples/ldap-stack-authelia"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../../examples/ldap-stack-authelia/versions.env
source "${example_dir}/versions.env"

: "${KUBECONFIG:?Set KUBECONFIG to the kubeconfig of a disposable kind cluster}"
test_cluster="${KIND_CLUSTER:-ldap-stack-authelia-test}"
test_namespace="${TEST_NAMESPACE:-ldap-stack-authelia-test}"
test_image="${OPENLDAP_TEST_IMAGE:-osixia/openldap:2.6.15-rc}"
if [ "$(kubectl config current-context)" != "kind-${test_cluster}" ]; then
    echo "Expected the disposable kind-${test_cluster} context" >&2
    exit 1
fi
if kubectl get namespace "${test_namespace}" >/dev/null 2>&1; then
    echo "Test namespace already exists: ${test_namespace}; use a fresh namespace" >&2
    exit 1
fi

test_tmp="$(mktemp -d)"
namespace_created=false
cleanup() {
    if [ "${namespace_created}" = true ]; then
        kubectl delete namespace "${test_namespace}" --wait=false >/dev/null
    fi
    rm -rf "${test_tmp:?}"
}
trap cleanup EXIT

python3 "${example_dir}/prepare.py" --output "${test_tmp}/generated"
helm pull authelia --repo https://charts.authelia.com \
    --version "${AUTHELIA_CHART_VERSION}" --destination "${test_tmp}"
for chart in openldap phpldapadmin; do
    helm lint "${chart_dir}/${chart}" --strict -f "${example_dir}/${chart}.yaml"
done
helm lint "${test_tmp}/authelia-${AUTHELIA_CHART_VERSION}.tgz" --strict \
    -f "${example_dir}/authelia.yaml"

for image in "${test_image}" phpldapadmin/phpldapadmin:2.3.11 ghcr.io/authelia/authelia:4.39.24; do
    docker image inspect "${image}" >/dev/null 2>&1 || docker pull "${image}"
    kind load docker-image "${image}" --name "${test_cluster}"
done
kubectl create namespace "${test_namespace}"
namespace_created=true
kubectl -n "${test_namespace}" apply -f "${test_tmp}/generated/resources.json"
helm install openldap "${chart_dir}/openldap" -n "${test_namespace}" \
    -f "${example_dir}/openldap.yaml" --set-string "image.repository=${test_image%:*}" \
    --set-string "image.tag=${test_image##*:}" --wait --timeout 3m
helm install phpldapadmin "${chart_dir}/phpldapadmin" -n "${test_namespace}" \
    -f "${example_dir}/phpldapadmin.yaml" --wait --timeout 3m
helm install authelia "${test_tmp}/authelia-${AUTHELIA_CHART_VERSION}.tgz" -n "${test_namespace}" \
    -f "${example_dir}/authelia.yaml" --wait --timeout 3m
python3 -u "${test_dir}/check.py" --namespace "${test_namespace}" \
    --credentials "${test_tmp}/generated/credentials.json"
