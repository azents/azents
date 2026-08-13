# WorkspaceRuntimeProfileResponse

One complete Workspace-owned Runtime choice.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_id** | **str** |  | 
**infrastructure_profile_id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**policy** | [**WorkspaceRuntimeProfilePolicy**](WorkspaceRuntimeProfilePolicy.md) |  | 
**infrastructure_network** | [**RuntimeNetworkProjection**](RuntimeNetworkProjection.md) |  | 
**effective_network** | [**RuntimeNetworkProjection**](RuntimeNetworkProjection.md) |  | 
**version** | **int** |  | 
**digest** | **str** |  | 
**available** | **bool** |  | 
**availability_reason_code** | **str** |  | 
**capability_revision_id** | **str** |  | 
**infrastructure_profile_version** | **int** |  | 
**compatible** | **bool** |  | 
**missing_capabilities** | **List[str]** |  | 
**incompatible_constraints** | **List[str]** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.workspace_runtime_profile_response import WorkspaceRuntimeProfileResponse

# TODO update the JSON string below
json = "{}"
# create an instance of WorkspaceRuntimeProfileResponse from a JSON string
workspace_runtime_profile_response_instance = WorkspaceRuntimeProfileResponse.from_json(json)
# print the JSON string representation of the object
print(WorkspaceRuntimeProfileResponse.to_json())

# convert the object into a dict
workspace_runtime_profile_response_dict = workspace_runtime_profile_response_instance.to_dict()
# create an instance of WorkspaceRuntimeProfileResponse from a dict
workspace_runtime_profile_response_from_dict = WorkspaceRuntimeProfileResponse.from_dict(workspace_runtime_profile_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


