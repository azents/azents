# CurrentMemberResponse

Current user workspace member info response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_user_id** | **str** | Current user WorkspaceUser ID | 
**role** | [**WorkspaceUserRole**](WorkspaceUserRole.md) | Current user role | 

## Example

```python
from azentspublicclient.models.current_member_response import CurrentMemberResponse

# TODO update the JSON string below
json = "{}"
# create an instance of CurrentMemberResponse from a JSON string
current_member_response_instance = CurrentMemberResponse.from_json(json)
# print the JSON string representation of the object
print(CurrentMemberResponse.to_json())

# convert the object into a dict
current_member_response_dict = current_member_response_instance.to_dict()
# create an instance of CurrentMemberResponse from a dict
current_member_response_from_dict = CurrentMemberResponse.from_dict(current_member_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


