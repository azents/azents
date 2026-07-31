# KubernetesPodProfileSpecV1

Kubernetes Pod Profile contract version 1.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_kind** | **str** |  | 
**contract_family** | **str** |  | 
**schema_version** | **int** |  | 
**runner_resources** | [**KubernetesContainerResources**](KubernetesContainerResources.md) |  | 
**workspace_volume** | [**KubernetesWorkspaceVolume**](KubernetesWorkspaceVolume.md) |  | 
**network_policy** | [**RuntimeNetworkPolicyModule**](RuntimeNetworkPolicyModule.md) |  | 
**service_account_name** | **str** |  | 
**scheduling** | [**KubernetesSchedulingModule**](KubernetesSchedulingModule.md) |  | 
**dind** | [**KubernetesDinDModule**](KubernetesDinDModule.md) |  | 

## Example

```python
from azentspublicclient.models.kubernetes_pod_profile_spec_v1 import KubernetesPodProfileSpecV1

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesPodProfileSpecV1 from a JSON string
kubernetes_pod_profile_spec_v1_instance = KubernetesPodProfileSpecV1.from_json(json)
# print the JSON string representation of the object
print(KubernetesPodProfileSpecV1.to_json())

# convert the object into a dict
kubernetes_pod_profile_spec_v1_dict = kubernetes_pod_profile_spec_v1_instance.to_dict()
# create an instance of KubernetesPodProfileSpecV1 from a dict
kubernetes_pod_profile_spec_v1_from_dict = KubernetesPodProfileSpecV1.from_dict(kubernetes_pod_profile_spec_v1_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


