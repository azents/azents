# KubernetesContainerResources

Explicit Kubernetes resources for one known Runtime component.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**cpu_request_millicores** | **int** |  | 
**cpu_limit_millicores** | **int** |  | 
**memory_request_bytes** | **int** |  | 
**memory_limit_bytes** | **int** |  | 

## Example

```python
from azentsadminclient.models.kubernetes_container_resources import KubernetesContainerResources

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesContainerResources from a JSON string
kubernetes_container_resources_instance = KubernetesContainerResources.from_json(json)
# print the JSON string representation of the object
print(KubernetesContainerResources.to_json())

# convert the object into a dict
kubernetes_container_resources_dict = kubernetes_container_resources_instance.to_dict()
# create an instance of KubernetesContainerResources from a dict
kubernetes_container_resources_from_dict = KubernetesContainerResources.from_dict(kubernetes_container_resources_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


