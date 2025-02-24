## Installing Flyte on Google Cloud

There are several install paths available for Flyte: sandbox, binary, core.
The sandox mode is usefull to test locally.
For a prod setup with a cluster than is less than 1000 nodes it seems best to use the binary one.
For a larger setup chose the core path.

Below we use the Helm flyte-binary install.

### Required Google Cloud ressources

Running Flyte on Google Cloud requires:
- a GKE cluster
- a Postgre database from Cloud SQL
- 2 file buckets from Cloud Storage
- a service-account email (here we use: flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com)
This needs to be setup prior to the install.
Note that if the db is not ready or if it is not reachable from the GKE cluster the install will get stuck trying to to connect to the db before completing.

### Workload Identity

**Remark** This section is the one that tricked me the most. It can be done at a later stage as it is not required to install Flyte and to open the web console or to interact with the gRPC services. However without this you wont be able to register your task and workflow code to the admin server.

Connect to your GKE cluster, for example if your cluster location is zonal:
```sh
gcloud container clusters get-credentials <CLUSTER_NAME> --zone=[CLUSTER_ZONE]
```

#### Cluster level

Your GKE clusters must have Workload Identity enabled.
Workload Identity is what makes the binding from KSA to GSA (see below section on service account) possible.
When enabled, you can annotate (this is done by the Helm chart) your Kubernetes service accounts with the corresponding Google Cloud service account. Then, when a pod uses that KSA, it can automatically assume the identity and permissions of the specified GSA.
Without enabling it, pods may end up using node-level credentials, which is less secure and harder to manage.

For example if your cluster location is zonal:
```sh
gcloud container clusters describe <CLUSTER_NAME> --zone <CLUSTER_ZONE> --format="value(workloadIdentityConfig.workloadPool)"
```
```console
<PROJECT_ID>.svc.id.goog
```
Otherwise update your cluster (this may take a couple minutes to complete):
```sh
gcloud container clusters update <CLUSTER_NAME> --zone <CLUSTER_ZONE> --workload-pool=<PROJECT_ID>.svc.id.goog   
```

#### Node Pool level

Individual node pools also need GKE Metadata Server to ensure that pods can securely exchange credentials with Google Cloud.
Without it, Workload Identity won't work, and your Flyte pods won't be able to authenticate as the Google Service Account (GSA).

List your Node Pools with:
```sh
gcloud container node-pools list --cluster <CLUSTER_NAME> --zone <CLUSTER_ZONE>
```
Then check that WI is enabled with:
```sh
gcloud container node-pools describe <NODE_POOL_NAME> --cluster <CLUSTER_NAME> --zone <CLUSTER_ZONE> --format="value(config.workloadMetadataConfig.mode)"
```
```console
GKE_METADATA
```
If it is not enable you can try to update with:
```sh
gcloud container node-pools update <NODE_POOL_NAME> \
  --cluster <CLUSTER_NAME> --zone <CLUSTER_ZONE> \
  --workload-metadata=GKE_METADATA
```

#### Test

Create a temporary test pod with the specification from debug-pod yaml:
```sh
kubectl apply -f debug-pod.yaml
```
```console
pod/debug-pod created
```

Run the following metadata request from inside the pod:
```sh
kubectl exec -it debug-pod -n flyte -- \
  curl -H "Metadata-Flavor: Google" \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email
```
```console
flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com
```

Also check the authScope covers "cloud-platform":
```sh
kubectl exec debug-pod -n flyte -- \
  curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com/token?scopes=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcloud-platform"
```
```console
{
  "access_token":<SOME_TOKEN_HERE>,
  "expires_in": 3450,
  "token_type": "Bearer"
}
```

Delete the test pod:
```sh
kubectl delete pod debug-pod -n flyte
```

### Install

Connect to your GKE cluster, for example if your cluster location is zonal:
```sh
gcloud container clusters get-credentials <CLUSTER_NAME> --zone=[CLUSTER_ZONE]
```


Create a dedicated *flyte* namespace:
```sh
kubectl create namespace flyte
```

Then add the flyteorg Helm repo:
```sh
helm repo add flyte https://flyteorg.github.io/flyte
helm repo update
```

For the install values, pick the available GKE template from the [FlyteOrg GitHub repo](https://github.com/flyteorg/flyte/blob/master/charts/flyte-binary/) and fill in the relevant values with respect to the PostgreSQL database, the file buckets, and the IAM service account emails.

```sh
helm install fb flyte/flyte-binary --namespace flyte --set fullnameOverride=flyte-binary --values values.yaml
```
Note the *fullnameOverride* option to avoid the release name (*fb* here) to be prefixed to all the pods and services names.

Check install was successful, you should be seeing a single "binary" pod:
```sh
kubectl get pods -n flyte
```

| NAME                               | READY | STATUS  | RESTARTS | AGE  |
|------------------------------------|-------|---------|----------|------|
| flyte-binary-75569594bb-744bt  | 1/1   | Running | 0        | 18h  |


### Checking Service Account mapping

#### Admin service pod

Under the flyte namespace we can see 2 KSA (service account internal to GKE), we need to check which one is being used by the pod:
```sh
kubectl get pod flyte-binary-75569594bb-744bt -n flyte -o yaml | grep serviceAccountName
```
```console
serviceAccountName: flyte-binary
```

Then we can check that this KSA is bound to the GSA (service account at GC level) we created and declared in the Helm deployment yaml file:
```sh
kubectl get serviceaccount flyte-binary -n flyte -o yaml
```
```console
apiVersion: v1
kind: ServiceAccount
metadata:
  annotations:
    iam.gke.io/gcp-service-account: flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com
    meta.helm.sh/release-name: fb
    meta.helm.sh/release-namespace: flyte
```

We also need to grant IAM permissions so that the GSA trusts the KSA for authentication:
```sh
gcloud iam service-accounts add-iam-policy-binding flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:<PROJECT_ID>.svc.id.goog[flyte/flyte-binary]"
```
You can check it worked fine with:
```sh
gcloud iam service-accounts get-iam-policy flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com \
  --flatten="bindings[]" \
  --filter="bindings.role:roles/iam.workloadIdentityUser" \
  --format="table(bindings.role, bindings.members)"
```
Expected output:
| ROLE                            | MEMBERS |
|---------------------------------|---------|
| roles/iam.workloadIdentityUser | ['serviceAccount:<PROJECT_ID>.svc.id.goog[flyte/flyte-binary]'] |


#### Execution pods

The admin KSA mapping allows to register tasks and workflows.
However when executing a job Flyte will use dedicated namespaces named based on the pattern "{project}-{domain}".
For each of them we expect the KSA to be "default" and we should check the KSA is mapped to the GSA via the relevant annotation like we just did for the Admin service.
And we also need to add "serviceAccount:<PROJECT_ID>.svc.id.goog[<namespace>/<default>]" to the members of the iam.workloadIdentityUser role binding.

When all the role bindings are done we can check:
```sh
gcloud iam service-accounts get-iam-policy flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com \
  --flatten="bindings[]" \
  --filter="bindings.role:roles/iam.workloadIdentityUser" \
  --format=yaml
```
```console
bindings:
  members:
  - serviceAccount:<PROJECT_ID>.svc.id.goog[flyte/flyte-binary]
  - serviceAccount:<PROJECT_ID>.svc.id.goog[flytesnacks-development/default]
  - serviceAccount:<PROJECT_ID>.svc.id.goog[flytesnacks-production/default]
  - serviceAccount:<PROJECT_ID>.svc.id.goog[flytesnacks-staging/default]
  role: roles/iam.workloadIdentityUser
```

### Granting roles to the GC Service Account

The list of roles to assign to our GSA is:
- iam.serviceAccountTokenCreator
- iam.workloadIdentityUser
- storage.admin (or at least storage.objectAdmin)
- iam.serviceAccountActor [not stricly needed but may help]

You can check wether they are assigned or not with:
```sh
gcloud projects get-iam-policy <PROJECT_ID> --flatten="bindings[].members" --format="table(bindings.role, bindings.members)" | grep flyte-sa@<PROJECT_ID>.iam.gserviceaccount.com
```

### Setup Load Balancer service

Next we add a Load Balander service to access flyte via a fixed internal IP adress.
First reserve an IP under your VPC via the Google Cloud console in the same location where your cluser is setup (here below we used IP 10.132.0.6). This IP will allow our other services (eg Cloud Run) to interact with Flyte.
Then edit the service yaml file with the relevant IP and apply:
```sh
kubectl apply -f service.yaml
```

Once that is done we can check the new LoadBalancer service is here with our IP showing as EXTERNAL-IP:
```sh
kubectl get svc -n flyte -o wide
```

| NAME                      | TYPE           | CLUSTER-IP       | EXTERNAL-IP  | PORT(S)                         | AGE  | SELECTOR  |
|---------------------------|---------------|-----------------|--------------|--------------------------------|------|-----------|
| flyte-binary-grpc      | ClusterIP      | 34.118.231.146  | <none>       | 8089/TCP                        | 18h  | app.kubernetes.io/component=flyte-binary, app.kubernetes.io/instance=fb, app.kubernetes.io/name=flyte-binary |
| flyte-binary-http      | ClusterIP      | 34.118.226.138  | <none>       | 8088/TCP                        | 18h  | app.kubernetes.io/component=flyte-binary, app.kubernetes.io/instance=fb, app.kubernetes.io/name=flyte-binary |
| flyte-binary-webhook   | ClusterIP      | 34.118.239.81   | <none>       | 443/TCP                         | 18h  | app.kubernetes.io/component=flyte-binary, app.kubernetes.io/instance=fb, app.kubernetes.io/name=flyte-binary |
| flyte-binary              | LoadBalancer   | 34.118.227.28   | 10.132.0.6   | 8088:32461/TCP,8089:31702/TCP   | 16h  | app.kubernetes.io/name=flyte-binary |


### Testing Web console and gRPC
You first need to port forward the load-balancer service 
```sh
kubectl port-forward -n flyte svc/flyte-binary 8088:8088 8089:8089
``` 

Then you should be able to open the web-console at:  http://localhost:8088/console

To test the gRPC you first need to install grpcurl utility for your terminal.
Start with listing available rpc services:
```sh
grpcurl -plaintext localhost:8089 list
```
```console
flyteidl.service.AdminService
flyteidl.service.DataProxyService
flyteidl.service.SignalService
grpc.health.v1.Health
grpc.reflection.v1.ServerReflection
grpc.reflection.v1alpha.ServerReflection
```

Then you can test the AdminService ListProjects method:
```sh
grpcurl -plaintext -d '{}' localhost:8089 flyteidl.service.AdminService.ListProjects
```
```console
{
  "projects": [
    {
      "id": "flytesnacks",
      "name": "flytesnacks",
      "domains": [
        {
          "id": "development",
          "name": "development"
        },
        {
          "id": "staging",
          "name": "staging"
        },
        {
          "id": "production",
          "name": "production"
        }
      ],
      "description": "Default project setup."
    }
  ]
}
```


### Sending tasks and workflows definitions to Flyte backend

#### Simple project without custom dependencies

Once your Flyte load-balancer is setup and the 8088 (REST) and 8089 (gRPC) traffic is forwarded to your machine you can start posting workflow to the backend and visualize them in the console.

First we can check the Flyte tasks and workflows are correctly defined by attempting to serialize the code:
```sh
pyflyte --pkgs workflows package -f
```

Then the registration to the admin backend is done with command "pyflyte register" as follow:
```sh
pyflyte --config=config.yaml register --project flytesnacks --domain development --version v1 workflows/wf1.py
```
Note the connextion details in the config.yaml file.

#### Projects with custom Docker images

##### Local build

The official documentation is here:
- https://flyte-next.readthedocs.io/en/latest/flytesnacks/examples/customizing_dependencies/image_spec.html
One of the confusing points to note about this feature is that you need to be running Docker locally for the image to be built.
If not the registration will still proceed by assuming the image is build already.

```sh
pyflyte --config=config.yaml register --project flytesnacks --domain development --version v1 --image=project_dkr/image.yaml project_dkr
```

##### Remote Docker build

The documentation also covers this approach to build the image locally:
- https://envd.tensorchord.ai/teams/context.html#start-remote-buildkitd-on-builder-machine
However I did not investigate it.
