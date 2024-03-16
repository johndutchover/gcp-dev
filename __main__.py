import pulumi
import pulumi_kubernetes as k8s
import pulumi_gcp as gcp
from pulumi import (
    Config,
    export,
    get_project,
    get_stack,
    Output,
    ResourceOptions,
)
from pulumi_gcp.config import project, zone
from pulumi_gcp.container import (
    Cluster,
    ClusterNodeConfigArgs,
    ClusterMasterAuthorizedNetworksConfigArgs,
    ClusterMasterAuthorizedNetworksConfigCidrBlockArgs,
    NodePool,
)
from pulumi_kubernetes import Provider
from pulumi_kubernetes.apps.v1 import Deployment, DeploymentSpecArgs
from pulumi_kubernetes.core.v1 import (
    ContainerArgs,
    ContainerPortArgs,
    PodSpecArgs,
    PodTemplateSpecArgs,
    Service,
    ServicePortArgs,
    ServiceSpecArgs,
)
from pulumi_kubernetes.meta.v1 import LabelSelectorArgs, ObjectMetaArgs

# Import the configuration values
config = pulumi.Config()

# Retrieve the value of "myEnvironment"
myValue = config.require("myEnvironment")

# Export the value as an output
pulumi.export("environment", myValue)

# Define the CIDR blocks
authorized_networks = {
    "ny_office_north": config.get("ny_office_north"),
}

# nodeCount is the number of cluster nodes to provision. Defaults to 3 if unspecified.
NODE_COUNT = config.get_int("node_count") or 2
# nodeMachineType is the machine type to use for cluster nodes. Defaults to n1-standard-1 if unspecified.
# See https://cloud.google.com/compute/docs/machine-types for more details on available machine types.
NODE_MACHINE_TYPE = config.get("node_machine_type") or "e2-medium"
# username is the admin username for the cluster.
USERNAME = config.get("username") or "admin"
# password is the password for the admin user in the cluster.
PASSWORD = config.get_secret("clusterAdminPwd")
# master version of GKE engine
MASTER_VERSION = config.get("master_version")

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

default = gcp.serviceaccount.Account(
    "default", account_id="service-account-id", display_name="Service Account"
)

# Try to retrieve an existing cluster; if not found, create a new one
try:
    existing_cluster = gcp.container.get_cluster(name="primary-cluster", location=zone)
except Exception as e:
    if "not found" in str(e):
        pulumi.log.info("Cluster not found, creating a new one.")
        primary = gcp.container.Cluster(
            "primary",
            deletion_protection=False,
            name="primary-cluster",
            location=zone,
            remove_default_node_pool=True,
            initial_node_count=NODE_COUNT,
        )
        pulumi.export(
            "kubeconfig",
            primary.name.apply(lambda name: gcp.container.get_kubeconfig(name, zone)),
        )
    else:
        pulumi.log.error(f"Error retrieving cluster: {e}")
        raise e  # Re-raise the exception for further handling if needed
else:
    pulumi.export("existing_cluster_name", existing_cluster.name)
    pulumi.export(
        "kubeconfig",
        existing_cluster.name.apply(
            lambda name: gcp.container.get_kubeconfig(name, zone)
        ),
    )

# In case of an existing cluster, you may want to export its properties.
# For instance, the `kubeconfig` can be obtained similarly to the new cluster creation case.
if "existing_cluster" in locals():
    pulumi.export("existing_cluster_name", existing_cluster.name)
    pulumi.export(
        "kubeconfig",
        existing_cluster.name.apply(lambda name: container.get_kubeconfig(name, zone)),
    )

primary_preemptible_nodes = gcp.container.NodePool(
    "primary_preemptible_nodes",
    name="my-node-pool",
    cluster=primary.id,
    node_count=NODE_COUNT,
    node_config=gcp.container.NodePoolNodeConfigArgs(
        preemptible=True,
        machine_type=NODE_MACHINE_TYPE,
        service_account=default.email,
        oauth_scopes=["https://www.googleapis.com/auth/cloud-platform"],
    ),
)

# Export the cluster's endpoint.
export("endpoint", primary.endpoint)

# Export the cluster's CA certificate.
export("ca_certificate", primary.master_auth.cluster_ca_certificate)


# Manufacture a GKE-style Kubeconfig. Note that this is slightly "different" because of the way GKE requires
# gcloud to be in the picture for cluster authentication (rather than using the client cert/key directly).
k8s_info = Output.all(primary.name, primary.endpoint, primary.master_auth)
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

# Create a Kubernetes Namespace if it doesn't exist
namespace = k8s.core.v1.Namespace(
    "crossplane-system-ns",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="crossplane-system",
    ),
    opts=pulumi.ResourceOptions(
        depends_on=[primary]
    ),  # Ensure namespace is created before deploying the chart
)

# Deploy Crossplane using the Helm chart
crossplane_chart = k8s.helm.v3.Chart(
    "crossplane",
    k8s.helm.v3.ChartOpts(
        chart="crossplane",
        version="1.6.1",  # Specify the version of Crossplane you want to install
        namespace=namespace.metadata.name,
        fetch_opts=k8s.helm.v3.FetchOpts(
            repo="https://charts.crossplane.io/stable",  # Crossplane Helm repository
        ),
    ),
    opts=pulumi.ResourceOptions(
        depends_on=[namespace]
    ),  # Ensure namespace is created before deploying the chart
)

# Export the required resources
pulumi.export("namespace", namespace.metadata.name)
pulumi.export("crossplane_chart", crossplane_chart._name)

# Create a canary deployment to test that this cluster works.
labels = {"app": "canary-{0}-{1}".format(get_project(), get_stack())}
canary = Deployment(
    "canary",
    spec=DeploymentSpecArgs(
        selector=LabelSelectorArgs(match_labels=labels),
        replicas=1,
        template=PodTemplateSpecArgs(
            metadata=ObjectMetaArgs(labels=labels),
            spec=PodSpecArgs(containers=[ContainerArgs(name="nginx", image="nginx")]),
        ),
    ),
    opts=ResourceOptions(provider=k8s_provider),
)

ingress = Service(
    "ingress",
    spec=ServiceSpecArgs(
        type="LoadBalancer",
        selector=labels,
        ports=[ServicePortArgs(port=80)],
    ),
    opts=ResourceOptions(provider=k8s_provider),
)

# Finally, export the kubeconfig so that the client can easily access the cluster.
export("kubeconfig", k8s_config)
# Export the k8s ingress IP to access the canary deployment
export(
    "ingress_ip",
    ingress.status.apply(lambda status: status.load_balancer.ingress[0].ip),
)
