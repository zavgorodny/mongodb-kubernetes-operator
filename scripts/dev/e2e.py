#!/usr/bin/env python

from kubernetes.client.rest import ApiException
from build_and_deploy_operator import (
    build_and_push_operator,
    deploy_operator,
    load_yaml_from_file,
)
import k8s_conditions
from dockerutil import build_and_push_image
from typing import Dict, Optional
from dev_config import load_config
from kubernetes import client, config
import argparse
import time
import os
import yaml

TEST_RUNNER_NAME = "test-runner"


def _load_testrunner_service_account() -> Optional[Dict]:
    return load_yaml_from_file("deploy/testrunner/service_account.yaml")


def _load_testrunner_role() -> Optional[Dict]:
    return load_yaml_from_file("deploy/testrunner/role.yaml")


def _load_testrunner_role_binding() -> Optional[Dict]:
    return load_yaml_from_file("deploy/testrunner/role_binding.yaml")


def _load_testrunner_cluster_role_binding() -> Optional[Dict]:
    return load_yaml_from_file("deploy/testrunner/cluster_role_binding.yaml")


def _prepare_testrunner_environment():
    """
    _prepare_testrunner_environment ensures the ServiceAccount,
    Role and ClusterRole and bindings are created for the test runner.
    """
    rbacv1 = client.RbacAuthorizationV1Api()
    corev1 = client.CoreV1Api()
    dev_config = load_config()

    _delete_testrunner_pod()

    print("Creating Role")
    k8s_conditions.ignore_if_already_exists(
        lambda: rbacv1.create_namespaced_role(
            dev_config.namespace, _load_testrunner_role()
        )
    )

    print("Creating Role Binding")
    k8s_conditions.ignore_if_already_exists(
        lambda: rbacv1.create_namespaced_role_binding(
            dev_config.namespace, _load_testrunner_role_binding()
        )
    )

    print("Creating Cluster Role Binding")
    k8s_conditions.ignore_if_already_exists(
        lambda: rbacv1.create_cluster_role_binding(
            _load_testrunner_cluster_role_binding()
        )
    )

    print("Creating ServiceAccount")
    k8s_conditions.ignore_if_already_exists(
        lambda: corev1.create_namespaced_service_account(
            dev_config.namespace, _load_testrunner_service_account()
        )
    )


def create_kube_config():
    """Replicates the local kubeconfig file (pointed at by KUBECONFIG),
    as a ConfigMap."""
    corev1 = client.CoreV1Api()
    print("Creating kube-config ConfigMap")

    svc = corev1.read_namespaced_service("kubernetes", "default")
    kube_config = os.getenv("KUBECONFIG")
    with open(kube_config) as fd:
        kube_config = yaml.safe_load(fd.read())

    kube_config["clusters"][0]["cluster"]["server"] = "https://" + svc.spec.cluster_ip
    kube_config = yaml.safe_dump(kube_config)
    data = {"kubeconfig": kube_config}
    config_map = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name="kube-config"), data=data
    )

    k8s_conditions.ignore_if_already_exists(
        lambda: corev1.create_namespaced_config_map("default", config_map)
    )


def build_and_push_testrunner(repo_url: str, tag: str, path: str):
    """
    build_and_push_testrunner builds and pushes the test runner
    image.
    """
    return build_and_push_image(repo_url, tag, path, "testrunner")


def build_and_push_e2e(repo_url: str, tag: str, path: str):
    """
    build_and_push_e2e builds and pushes the e2e image.
    """
    return build_and_push_image(repo_url, tag, path, "e2e")


def build_and_push_prehook(repo_url: str, tag: str, path: str):
    """
    build_and_push_prehook builds and pushes the pre-stop-hook image.
    """
    return build_and_push_image(repo_url, tag, path, "prehook")


def _delete_testrunner_pod() -> None:
    """
    _delete_testrunner_pod deletes the test runner pod
    if it already exists.
    """
    dev_config = load_config()
    corev1 = client.CoreV1Api()
    k8s_conditions.ignore_if_doesnt_exist(
        lambda: corev1.delete_namespaced_pod(TEST_RUNNER_NAME, dev_config.namespace)
    )


def create_test_runner_pod(test: str):
    """
    create_test_runner_pod creates the pod which will run all of the tests.
    """
    dev_config = load_config()
    corev1 = client.CoreV1Api()
    pod_body = _get_testrunner_pod_body(test)

    if not k8s_conditions.wait(
        lambda: corev1.list_namespaced_pod(
            dev_config.namespace, field_selector=f"metadata.name=={TEST_RUNNER_NAME}"
        ),
        lambda pod_list: len(pod_list.items) == 0,
        timeout=10,
        sleep_time=0.5,
    ):

        raise Exception(
            "Execution timed out while waiting for the existing pod to be deleted"
        )

    return corev1.create_namespaced_pod(dev_config.namespace, body=pod_body)


def wait_for_pod_to_be_running(corev1, name, namespace):
    print("Waiting for pod to be running")
    if not k8s_conditions.wait(
        lambda: corev1.read_namespaced_pod(name, namespace),
        lambda pod: pod.status.phase == "Running",
        sleep_time=5,
        timeout=50,
        exceptions_to_ignore=ApiException,
    ):
        raise Exception("Pod never got into Running state!")


def _get_testrunner_pod_body(test: str) -> Dict:
    dev_config = load_config()
    return {
        "kind": "Pod",
        "metadata": {"name": TEST_RUNNER_NAME, "namespace": dev_config.namespace,},
        "spec": {
            "restartPolicy": "Never",
            "serviceAccountName": TEST_RUNNER_NAME,
            "containers": [
                {
                    "name": TEST_RUNNER_NAME,
                    "image": f"{dev_config.repo_url}/{TEST_RUNNER_NAME}",
                    "imagePullPolicy": "Always",
                    "command": [
                        "./runner",
                        "--operatorImage",
                        f"{dev_config.repo_url}/mongodb-kubernetes-operator",
                        "--preHookImage",
                        f"{dev_config.repo_url}/prehook",
                        "--testImage",
                        f"{dev_config.repo_url}/e2e",
                        f"--test={test}",
                        f"--namespace={dev_config.namespace}",
                    ],
                }
            ],
        },
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", help="Name of the test to run")
    parser.add_argument(
        "--skip-operator-install",
        help="Do not install the Operator, assumes one is installed already",
        type=bool,
        default=False,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config.load_kube_config()
    dev_config = load_config()
    create_kube_config()

    if not args.skip_operator_install:
        build_and_push_operator(
            dev_config.repo_url,
            f"{dev_config.repo_url}/mongodb-kubernetes-operator",
            ".",
        )
        deploy_operator()

    build_and_push_testrunner(
        dev_config.repo_url, f"{dev_config.repo_url}/{TEST_RUNNER_NAME}", "."
    )
    build_and_push_e2e(dev_config.repo_url, f"{dev_config.repo_url}/e2e", ".")
    build_and_push_prehook(dev_config.repo_url, f"{dev_config.repo_url}/prehook", ".")

    _prepare_testrunner_environment()

    pod = create_test_runner_pod(args.test)
    corev1 = client.CoreV1Api()

    wait_for_pod_to_be_running(corev1, TEST_RUNNER_NAME, dev_config.namespace)

    # stream all of the pod output as the pod is running
    for line in corev1.read_namespaced_pod_log(
        TEST_RUNNER_NAME, dev_config.namespace, follow=True, _preload_content=False
    ).stream():
        print(line.decode("utf-8").rstrip())


if __name__ == "__main__":
    main()
