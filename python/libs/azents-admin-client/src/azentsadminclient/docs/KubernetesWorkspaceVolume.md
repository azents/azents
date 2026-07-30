# KubernetesWorkspaceVolume

Existing per-Runtime Workspace PVC inputs.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**storage_class_name** | **str** |  | 
**storage_request_bytes** | **int** |  | 

## Example

```python
from azentsadminclient.models.kubernetes_workspace_volume import KubernetesWorkspaceVolume

# TODO update the JSON string below
json = "{}"
# create an instance of KubernetesWorkspaceVolume from a JSON string
kubernetes_workspace_volume_instance = KubernetesWorkspaceVolume.from_json(json)
# print the JSON string representation of the object
print(KubernetesWorkspaceVolume.to_json())

# convert the object into a dict
kubernetes_workspace_volume_dict = kubernetes_workspace_volume_instance.to_dict()
# create an instance of KubernetesWorkspaceVolume from a dict
kubernetes_workspace_volume_from_dict = KubernetesWorkspaceVolume.from_dict(kubernetes_workspace_volume_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


