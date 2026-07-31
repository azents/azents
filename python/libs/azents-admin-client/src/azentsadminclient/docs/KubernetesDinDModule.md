# KubernetesDinDModule

Privileged DinD topology owned by a Platform Pod Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**engine_resources** | [**KubernetesContainerResources**](KubernetesContainerResources.md) |  | 
**docker_storage_bytes** | **int** |  | 
**shared_temporary_storage_bytes** | **int** |  | 

## Example

```python
from azentsadminclient.models.kubernetes_din_d_module import KubernetesDinDModule

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesDinDModule from a JSON string
kubernetes_din_d_module_instance = KubernetesDinDModule.from_json(json)
# print the JSON string representation of the object
print(KubernetesDinDModule.to_json())

# convert the object into a dict
kubernetes_din_d_module_dict = kubernetes_din_d_module_instance.to_dict()
# create an instance of KubernetesDinDModule from a dict
kubernetes_din_d_module_from_dict = KubernetesDinDModule.from_dict(kubernetes_din_d_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


