import pulumi
import pulumi_gcp as gcp

# Configure the GCP project and zone
project_id = "premium-botany-414502"
zone = "us-east4-c"

# Define pub ssh key
ssh_key = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMLbPkjTQ6CTLLzwNBXy6qfjLx9Xh+Lq004Ko7bS++Yn"
)

# Protect the VPC network from accidental deletion
network = gcp.compute.Network("protected-network",
                                        auto_create_subnetworks=True,
                                        project=project_id,
                                        opts=pulumi.ResourceOptions(protect=False))

# Create a GCP firewall rule that allows SSH traffic from a given IP range
firewall = gcp.compute.Firewall(
    "firewall",
    network=network.id,
    allows=[
        {
            "protocol": "tcp",
            "ports": ["22"],
        }
    ],
    source_ranges=["71.247.198.14/32", "35.235.240.0/20"],
)

# Create a new GCP compute instance
instance = gcp.compute.Instance(
    "instance",
    machine_type="e2-medium",
    zone=zone,
    boot_disk=gcp.compute.InstanceBootDiskArgs(
        initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(
            image="ubuntu-os-cloud/ubuntu-minimal-2204-lts"
        )
    ),
    # Setting the scheduling option to preemptible for cost savings
    scheduling=gcp.compute.InstanceSchedulingArgs(
        preemptible=True,
        automatic_restart=False
    ),
    network_interfaces=[
        gcp.compute.InstanceNetworkInterfaceArgs(
            network=network.id,
            access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()],
        )
    ],
    service_account=gcp.compute.InstanceServiceAccountArgs(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    ),
    opts=pulumi.ResourceOptions(protect=False)
)

# A key set in project metadata is propagated to every instance in the project.
# This resource configuration is prone to causing frequent diffs
# as Google adds SSH Keys when the SSH Button is pressed in the console.
# It is better to use OS Login instead.
my_ssh_key = gcp.compute.ProjectMetadata(
    "mySshKey",
    metadata={
        "ssh-keys": """john:ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMLbPkjTQ6CTLLzwNBXy6qfjLx9Xh+Lq004Ko7bS++Yn""",
    },
)

# Export the external IP of the compute instance
pulumi.export(
    "instance_external_ip", instance.network_interfaces[0].access_configs[0].nat_ip
)
pulumi.export('protected_network', network.name)
pulumi.export('network_id', network.id)
