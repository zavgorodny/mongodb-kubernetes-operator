#!/usr/bin/env bash
set -Eeou pipefail


# adapted from https://kind.sigs.k8s.io/docs/user/local-registry/
# create registry container unless it already exists
reg_name='kind-registry'
reg_port='5000'
running="$(docker inspect -f '{{.State.Running}}' "${reg_name}" 2>/dev/null || true)"
if [ "${running}" != 'true' ]; then
  docker run \
    -d --restart=always -p "${reg_port}:${reg_port}" --name "${reg_name}" \
    registry:2
fi

ip="$(docker inspect kind-registry -f '{{.NetworkSettings.IPAddress}}')"

# create a cluster with the local registry enabled in containerd
cat <<EOF | kind create cluster --kubeconfig ~/.kube/kind --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."localhost:${reg_port}"]
    endpoint = ["http://${ip}:${reg_port}"]
EOF
