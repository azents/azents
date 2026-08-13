# KubernetesPodProfileSpecV3

Kubernetes Pod Profile contract version 3.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_kind** | **str** |  | 
**contract_family** | **str** |  | 
**schema_version** | **int** |  | 
**runner_resources** | [**KubernetesContainerResources**](KubernetesContainerResources.md) |  | 
**workspace_volume** | [**KubernetesWorkspaceVolume**](KubernetesWorkspaceVolume.md) |  | 
**network_access** | [**RuntimeNetworkAccess**](RuntimeNetworkAccess.md) |  | 
**service_account_name** | **str** |  | 
**scheduling** | [**KubernetesSchedulingModule**](KubernetesSchedulingModule.md) |  | 
**dind** | [**KubernetesDinDModule**](KubernetesDinDModule.md) |  | 

## Example

```python
from azentspublicclient.models.kubernetes_pod_profile_spec_v3 import KubernetesPodProfileSpecV3

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesPodProfileSpecV3 from a JSON string
kubernetes_pod_profile_spec_v3_instance = KubernetesPodProfileSpecV3.from_json(json)
# print the JSON string representation of the object
print(KubernetesPodProfileSpecV3.to_json())

# convert the object into a dict
kubernetes_pod_profile_spec_v3_dict = kubernetes_pod_profile_spec_v3_instance.to_dict()
# create an instance of KubernetesPodProfileSpecV3 from a dict
kubernetes_pod_profile_spec_v3_from_dict = KubernetesPodProfileSpecV3.from_dict(kubernetes_pod_profile_spec_v3_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


