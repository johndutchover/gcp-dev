# GKE

## Deployed with Pulumi

Based on [_Google Kubernetes Engine (GKE) with a Canary Deployment_](https://github.com/pulumi/examples/tree/master/gcp-py-gke)

### Prerequisites
- Pulumi CLI
- GCP SDK

[Install kubectl authentication plugin](https://cloud.google.com/blog/products/containers-kubernetes/kubectl-auth-changes-in-gke):
>`gcloud components install gke-gcloud-auth-plugin`

### Pulumi config

#### Set GCP parameters in Pulumi

```bash
pulumi config set gcp:project <project_name>
pulumi config set gcp:zone
pulumi config set master_version 1.27.8-gke.1067004
pulumi config set --secret clusterAdminPwd <password>
```

#### Run Pulumi
`pulumi up`
