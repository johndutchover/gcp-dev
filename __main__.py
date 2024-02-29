import pulumi
import pulumi_kubernetes as k8s
import pulumi_gcp as gcp
from pulumi import Config, export, get_project, get_stack, Output, ResourceOptions
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
primary = gcp.container.Cluster(
    "primary",
    deletion_protection=False,
    name="primary-cluster",
    location=zone,
    remove_default_node_pool=True,
    initial_node_count=NODE_COUNT,
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

# # Provide the name of your application
# app_name = "hello-world"
#
# # Define a Kubernetes Deployment
# deployment = k8s.apps.v1.Deployment(
#     app_name,
#     metadata=k8s.meta.v1.ObjectMetaArgs(
#         name=app_name,
#     ),
#     spec=k8s.apps.v1.DeploymentSpecArgs(
#         replicas=1,
#         selector=k8s.meta.v1.LabelSelectorArgs(match_labels={"app": app_name}),
#         template=k8s.core.v1.PodTemplateSpecArgs(
#             metadata=k8s.meta.v1.ObjectMetaArgs(
#                 labels={"app": app_name},
#             ),
#             spec=k8s.core.v1.PodSpecArgs(
#                 containers=[
#                     k8s.core.v1.ContainerArgs(
#                         name=app_name,
#                         image="us-docker.pkg.dev/google-samples/containers/gke/hello-app:1.0",
#                         ports=[k8s.core.v1.ContainerPortArgs(container_port=8080)],
#                     ),
#                 ],
#             ),
#         ),
#     ),
# )

# Make a Kubernetes provider instance that uses our cluster from above.
k8s_provider = Provider("gke_k8s", kubeconfig=k8s_config)

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
