# WorkspaceRuntimeProfilePolicy


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**schema_version** | **int** |  | 
**network_restriction** | [**WorkspaceRuntimeNetworkRestriction**](WorkspaceRuntimeNetworkRestriction.md) |  | 

## Example

```python
from azentsadminclient.models.workspace_runtime_profile_policy import WorkspaceRuntimeProfilePolicy

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfilePolicy from a JSON string
workspace_runtime_profile_policy_instance = WorkspaceRuntimeProfilePolicy.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfilePolicy.to_json())

# convert the object into a dict
workspace_runtime_profile_policy_dict = workspace_runtime_profile_policy_instance.to_dict()
# create an instance of WorkspaceRuntimeProfilePolicy from a dict
workspace_runtime_profile_policy_from_dict = WorkspaceRuntimeProfilePolicy.from_dict(workspace_runtime_profile_policy_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


