# PersonalToolkitResponse

Allowlisted personal configuration without credentials or owning Workspace.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**toolkit_type** | **str** |  | 
**slug** | **str** |  | 
**name** | **str** |  | 
**description** | **str** |  | 
**config** | **object** |  | 
**prompt** | **str** |  | 
**has_credentials** | **bool** | Whether credentials exist | [optional] [default to False]
**enabled** | **bool** |  | 
**always_expose_tools** | **bool** |  | 
**oauth_connection** | [**MCPOAuthConnectionSummaryResponse**](MCPOAuthConnectionSummaryResponse.md) |  | [optional] 
**authorization_state** | [**GitHubPlatformAuthorizationStateResponse**](GitHubPlatformAuthorizationStateResponse.md) |  | [optional] 
**github_user_connection** | [**GitHubUserConnectionSummaryResponse**](GitHubUserConnectionSummaryResponse.md) |  | [optional] 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 
**owner** | [**UserToolkitOwner**](UserToolkitOwner.md) |  | 
**access_mode** | [**PersonalToolkitAccessMode**](PersonalToolkitAccessMode.md) |  | 
**selected_agent_ids** | **List[str]** |  | 
**readiness** | **str** |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_response import PersonalToolkitResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitResponse from a JSON string
personal_toolkit_response_instance = PersonalToolkitResponse.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitResponse.to_json())

# convert the object into a dict
personal_toolkit_response_dict = personal_toolkit_response_instance.to_dict()
# create an instance of PersonalToolkitResponse from a dict
personal_toolkit_response_from_dict = PersonalToolkitResponse.from_dict(personal_toolkit_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


