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
from pulumi_kubernetes import Provider

# Import the configuration values
config = pulumi.Config()

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

# Retrieve the value of "myEnvironment"
my_value = config.require("myEnvironment")

# Export the value as an output
pulumi.export("environment", my_value)

# Define the CIDR blocks
authorized_networks = {
    "ny_office": config.get("ny_office"),
}

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

# Manufacture a GKE-style Kubeconfig. Note that this is slightly "different" because of the way GKE requires
# gcloud to be in the picture for cluster authentication (rather than using the client cert/key directly).
k8s_info = Output.all(
    primary_cluster.name, primary_cluster.endpoint, primary_cluster.master_auth
)

k8s_config = k8s_info.apply(
    lambda info: """apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: {0}
    server: https://{1}
  name: {2}
contexts:
- context:
    cluster: {2}
    user: {2}
  name: {2}
current-context: {2}
kind: Config
preferences: {{}}
users:
- name: {2}
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: gke-gcloud-auth-plugin
      installHint: Install gke-gcloud-auth-plugin for use with kubectl by following
        https://cloud.google.com/blog/products/containers-kubernetes/kubectl-auth-changes-in-gke
      provideClusterInfo: true
""".format(
        info[2]["cluster_ca_certificate"],
        info[1],
        "{0}_{1}_{2}".format(project, zone, info[0]),
    )
)

# Make a Kubernetes provider instance that uses our cluster from above.
k8s_provider = Provider("gke_k8s", kubeconfig=k8s_config)

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

# Export cluster information
pulumi.export("cluster_name", primary_cluster.name)
pulumi.export("cluster_endpoint", primary_cluster.endpoint)
pulumi.export(
    "cluster_ca_certificate", primary_cluster.master_auth.cluster_ca_certificate
)

# Export the cluster's endpoint.
export("endpoint", primary_cluster.endpoint)

# Export the cluster's CA certificate.
export("ca_certificate", primary_cluster.master_auth.cluster_ca_certificate)
