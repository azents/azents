# AdminWorkspaceRuntimeProfileDetailResponse

System-Admin read-only Workspace Runtime Profile detail.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_id** | **str** |  | 
**workspace_name** | **str** |  | 
**workspace_handle** | **str** |  | 
**profile_id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**policy** | [**WorkspaceRuntimeProfilePolicyV1**](WorkspaceRuntimeProfilePolicyV1.md) |  | 
**version** | **int** |  | 
**digest** | **str** |  | 
**provider_id** | **str** |  | 
**provider_display_name** | **str** |  | 
**provider_kind** | **str** |  | 
**infrastructure_profile_id** | **str** |  | 
**infrastructure_profile_display_name** | **str** |  | 
**infrastructure_profile_kind** | **str** |  | 
**infrastructure_profile_lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**infrastructure_profile_version** | **int** |  | 
**selected_agent_count** | **int** |  | 
**running_runtime_count** | **int** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.admin_workspace_runtime_profile_detail_response import AdminWorkspaceRuntimeProfileDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AdminWorkspaceRuntimeProfileDetailResponse from a JSON string
admin_workspace_runtime_profile_detail_response_instance = AdminWorkspaceRuntimeProfileDetailResponse.from_json(json)
# print the JSON string representation of the object
print(AdminWorkspaceRuntimeProfileDetailResponse.to_json())

# convert the object into a dict
admin_workspace_runtime_profile_detail_response_dict = admin_workspace_runtime_profile_detail_response_instance.to_dict()
# create an instance of AdminWorkspaceRuntimeProfileDetailResponse from a dict
admin_workspace_runtime_profile_detail_response_from_dict = AdminWorkspaceRuntimeProfileDetailResponse.from_dict(admin_workspace_runtime_profile_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


