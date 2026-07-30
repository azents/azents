# KubernetesSchedulingModule

Typed initial Kubernetes scheduling controls.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**node_selector** | **Dict[str, str]** |  | [optional] 
**tolerations** | [**List[KubernetesToleration]**](KubernetesToleration.md) |  | [optional] [default to []]

## Example

```python
from azentsadminclient.models.kubernetes_scheduling_module import KubernetesSchedulingModule

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesSchedulingModule from a JSON string
kubernetes_scheduling_module_instance = KubernetesSchedulingModule.from_json(json)
# print the JSON string representation of the object
print(KubernetesSchedulingModule.to_json())

# convert the object into a dict
kubernetes_scheduling_module_dict = kubernetes_scheduling_module_instance.to_dict()
# create an instance of KubernetesSchedulingModule from a dict
kubernetes_scheduling_module_from_dict = KubernetesSchedulingModule.from_dict(kubernetes_scheduling_module_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


