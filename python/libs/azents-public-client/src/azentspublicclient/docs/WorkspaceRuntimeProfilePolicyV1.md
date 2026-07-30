# WorkspaceRuntimeProfilePolicyV1

Workspace-owned restrictions attached to one Runtime Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**schema_version** | **int** |  | 
**network_restriction** | [**RuntimeNetworkPolicyModule**](RuntimeNetworkPolicyModule.md) |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_policy_v1 import WorkspaceRuntimeProfilePolicyV1

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfilePolicyV1 from a JSON string
workspace_runtime_profile_policy_v1_instance = WorkspaceRuntimeProfilePolicyV1.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfilePolicyV1.to_json())

# convert the object into a dict
workspace_runtime_profile_policy_v1_dict = workspace_runtime_profile_policy_v1_instance.to_dict()
# create an instance of WorkspaceRuntimeProfilePolicyV1 from a dict
workspace_runtime_profile_policy_v1_from_dict = WorkspaceRuntimeProfilePolicyV1.from_dict(workspace_runtime_profile_policy_v1_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


