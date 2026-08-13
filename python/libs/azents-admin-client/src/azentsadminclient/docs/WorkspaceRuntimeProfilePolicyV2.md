# WorkspaceRuntimeProfilePolicyV2

Workspace-owned hierarchical network restriction.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**schema_version** | **int** |  | 
**network_restriction** | [**WorkspaceRuntimeNetworkRestriction**](WorkspaceRuntimeNetworkRestriction.md) |  | 

## Example

```python
from azentsadminclient.models.workspace_runtime_profile_policy_v2 import WorkspaceRuntimeProfilePolicyV2

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfilePolicyV2 from a JSON string
workspace_runtime_profile_policy_v2_instance = WorkspaceRuntimeProfilePolicyV2.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfilePolicyV2.to_json())

# convert the object into a dict
workspace_runtime_profile_policy_v2_dict = workspace_runtime_profile_policy_v2_instance.to_dict()
# create an instance of WorkspaceRuntimeProfilePolicyV2 from a dict
workspace_runtime_profile_policy_v2_from_dict = WorkspaceRuntimeProfilePolicyV2.from_dict(workspace_runtime_profile_policy_v2_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


