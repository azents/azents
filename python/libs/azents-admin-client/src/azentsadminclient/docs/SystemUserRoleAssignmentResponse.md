# SystemUserRoleAssignmentResponse

System role assignment response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**user_id** | **str** | Assigned User ID | 
**role** | [**SystemUserRole**](SystemUserRole.md) | System role | 
**granted_by_user_id** | **str** |  | 
**granted_at** | **datetime** | Grant time | 

## Example

```python
from azentsadminclient.models.system_user_role_assignment_response import SystemUserRoleAssignmentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemUserRoleAssignmentResponse from a JSON string
system_user_role_assignment_response_instance = SystemUserRoleAssignmentResponse.from_json(json)
# print the JSON string representation of the object
print(SystemUserRoleAssignmentResponse.to_json())

# convert the object into a dict
system_user_role_assignment_response_dict = system_user_role_assignment_response_instance.to_dict()
# create an instance of SystemUserRoleAssignmentResponse from a dict
system_user_role_assignment_response_from_dict = SystemUserRoleAssignmentResponse.from_dict(system_user_role_assignment_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


