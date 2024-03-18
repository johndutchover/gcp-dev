# GKE

## Deployed with Pulumi

Based on [_Google Kubernetes Engine (GKE) with a Canary Deployment_](https://github.com/pulumi/examples/tree/master/gcp-py-gke)

### Prerequisites
- Pulumi CLI
- GCP SDK
- [gcloud CLI](https://cloud.google.com/sdk/docs/install)

[Install kubectl authentication plugin](https://cloud.google.com/blog/products/containers-kubernetes/kubectl-auth-changes-in-gke):
>`gcloud components install gke-gcloud-auth-plugin`

### GCloud CLI
- [Authorize a service account using service account impersonation](https://cloud.google.com/sdk/docs/authorizing)
  - `gcloud container clusters get-credentials primary-cluster --zone us-east4-b --project <project_name>
- [Authenticate using the CLI](https://www.pulumi.com/registry/packages/gcp/installation-configuration/#authenticate-using-the-cli)

### Pulumi config

#### Configure stack `gcp-dev`
```bash
pulumi config set --secret clusterAdminPwd <password>
pulumi config set gcp-dev:google-native:
pulumi config set gcp-dev:k8s_helm_chart_name:
pulumi config set gcp-dev:k8s_helm_chart_version:
pulumi config set gcp-dev:k8s_helm_repo_url:
pulumi config set gcp-dev:master_version:
pulumi config set gcp-dev:min_master_version:
pulumi config set gcp-dev:myEnvironment:
pulumi config set gcp-dev:namespace:
pulumi config set gcp-dev:namespace_name:
pulumi config set gcp-dev:node_count:
pulumi config set gcp-dev:ny_office:
````

#### Set GCP parameters in Pulumi

```bash
pulumi config set gcp:credentials
pulumi config set gcp:project <project_name>
pulumi config set gcp:zone
```

#### Run Pulumi
`pulumi up`
