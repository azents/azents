# KubernetesToleration

Typed Kubernetes toleration supported by Pod Profile v1.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**key** | **str** |  | 
**operator** | **str** |  | 
**value** | **str** |  | 
**effect** | **str** |  | 
**toleration_seconds** | **int** |  | 

## Example

```python
from azentsadminclient.models.kubernetes_toleration import KubernetesToleration

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesToleration from a JSON string
kubernetes_toleration_instance = KubernetesToleration.from_json(json)
# print the JSON string representation of the object
print(KubernetesToleration.to_json())

# convert the object into a dict
kubernetes_toleration_dict = kubernetes_toleration_instance.to_dict()
# create an instance of KubernetesToleration from a dict
kubernetes_toleration_from_dict = KubernetesToleration.from_dict(kubernetes_toleration_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


