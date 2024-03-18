import pulumi
import pulumi_kubernetes as k8s
import pulumi_gcp as gcp
from pulumi import Config, export, get_project, get_stack, Output, ResourceOptions
from pulumi_gcp.config import project, zone
from pulumi_gcp.container import (
    Cluster,
    ClusterMasterAuthorizedNetworksConfigArgs,
    ClusterMasterAuthorizedNetworksConfigCidrBlockArgs,
    NodePool,
)
from pulumi_kubernetes.helm.v3 import ChartOpts, FetchOpts

# Import the configuration values
config = pulumi.Config()

# Retrieve the value of "myEnvironment"
my_value = config.require("myEnvironment")

# Export the value as an output
pulumi.export("environment", my_value)

# Define the CIDR blocks
authorized_networks = {
    "ny_office": config.get("ny_office"),
}

# Define constants
NODE_COUNT = config.get_int("node_count") or 2
NODE_MACHINE_TYPE = config.get("node_machine_type") or "e2-medium"
USERNAME = config.get("username") or "admin"
PASSWORD = config.get_secret("clusterAdminPwd")
MASTER_VERSION = config.get("master_version")
NAMESPACE_NAME = config.get("namespace_name") or "default"
CHART_NAME = config.get("chart_name") or "crossplane"
CHART_VERSION = config.get("chart_version") or "1.15.1"
CROSSPLANE_HELM_REPO_URL = (
    config.get("k8s_helm_repo_url") or "https://charts.crossplane.io"
)

# Define the master authorized networks config
master_authorized_networks_config = ClusterMasterAuthorizedNetworksConfigArgs(
    cidr_blocks=[
        ClusterMasterAuthorizedNetworksConfigCidrBlockArgs(
            cidr_block=cidr,
            display_name=name,
        )
        for name, cidr in authorized_networks.items()
    ],
)

# Create or retrieve the GCP service account
default_service_account = gcp.serviceaccount.Account(
    "default",
    account_id="service-account-id",
    display_name="Service Account",
)

# Create or retrieve the GCP cluster
primary_cluster = Cluster(
    "primary-cluster",
    name="primary-cluster",
    location=zone,
    initial_node_count=NODE_COUNT,
    remove_default_node_pool=True,
    master_authorized_networks_config=master_authorized_networks_config,
    deletion_protection=False,
)

# Export cluster information
pulumi.export("cluster_name", primary_cluster.name)
pulumi.export("cluster_endpoint", primary_cluster.endpoint)
pulumi.export(
    "cluster_ca_certificate", primary_cluster.master_auth.cluster_ca_certificate
)

# Create or retrieve the GCP node pool
primary_node_pool = NodePool(
    "primary-node-pool",
    cluster=primary_cluster.name,
    node_count=NODE_COUNT,
    node_config=gcp.container.NodePoolNodeConfigArgs(
        preemptible=True,
        machine_type=NODE_MACHINE_TYPE,
        service_account=default_service_account.email,
        oauth_scopes=["https://www.googleapis.com/auth/cloud-platform"],
    ),
)

# Fetch the kubeconfig for the cluster
kubeconfig = primary_cluster.master_auth.cluster_ca_certificate

# Create the Kubernetes provider using the cluster's kubeconfig
k8s_provider = k8s.Provider(
    "gke_k8s", kubeconfig=primary_cluster.master_auth.cluster_ca_certificate
)

# Define the canary deployment
canary = k8s.apps.v1.Deployment(
    "canary",
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=1,
        selector=k8s.meta.v1.LabelSelectorArgs(match_labels={"app": "canary"}),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(labels={"app": "canary"}),
            spec=k8s.core.v1.PodSpecArgs(
                containers=[k8s.core.v1.ContainerArgs(name="nginx", image="nginx")]
            ),
        ),
    ),
    opts=ResourceOptions(provider=k8s_provider),
)

# Define the ingress service
ingress = k8s.core.v1.Service(
    "ingress",
    spec=k8s.core.v1.ServiceSpecArgs(
        type="LoadBalancer",
        selector={"app": "canary"},
        ports=[k8s.core.v1.ServicePortArgs(port=80)],
    ),
    opts=ResourceOptions(provider=k8s_provider),
)

# Export the kubeconfig for the cluster
pulumi.export("kubeconfig", primary_cluster.node_config)

# Export the ingress ip
pulumi.export(
    "ingress_ip",
    ingress.status.apply(lambda status: status.load_balancer.ingress[0].ip),
)

# Export the cluster's endpoint.
export("endpoint", primary_cluster.endpoint)

# Export the cluster's CA certificate.
export("ca_certificate", primary_cluster.master_auth.cluster_ca_certificate)
