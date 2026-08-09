# KubernetesPodProfileSpecV2

Kubernetes Pod Profile contract version 2.

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
**process_containment** | [**RuntimeProcessContainmentModuleV1**](RuntimeProcessContainmentModuleV1.md) |  | 

## Example

```python
from azentsadminclient.models.kubernetes_pod_profile_spec_v2 import KubernetesPodProfileSpecV2

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesPodProfileSpecV2 from a JSON string
kubernetes_pod_profile_spec_v2_instance = KubernetesPodProfileSpecV2.from_json(json)
# print the JSON string representation of the object
print(KubernetesPodProfileSpecV2.to_json())

# convert the object into a dict
kubernetes_pod_profile_spec_v2_dict = kubernetes_pod_profile_spec_v2_instance.to_dict()
# create an instance of KubernetesPodProfileSpecV2 from a dict
kubernetes_pod_profile_spec_v2_from_dict = KubernetesPodProfileSpecV2.from_dict(kubernetes_pod_profile_spec_v2_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


