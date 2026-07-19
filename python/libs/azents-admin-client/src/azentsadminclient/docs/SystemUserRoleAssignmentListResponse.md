# SystemUserRoleAssignmentListResponse

System role assignment list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SystemUserRoleAssignmentResponse]**](SystemUserRoleAssignmentResponse.md) | System role assignments | 
**total** | **int** | Total assignment count | 

## Example

```python
from azentsadminclient.models.system_user_role_assignment_list_response import SystemUserRoleAssignmentListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemUserRoleAssignmentListResponse from a JSON string
system_user_role_assignment_list_response_instance = SystemUserRoleAssignmentListResponse.from_json(json)
# print the JSON string representation of the object
print(SystemUserRoleAssignmentListResponse.to_json())

# convert the object into a dict
system_user_role_assignment_list_response_dict = system_user_role_assignment_list_response_instance.to_dict()
# create an instance of SystemUserRoleAssignmentListResponse from a dict
system_user_role_assignment_list_response_from_dict = SystemUserRoleAssignmentListResponse.from_dict(system_user_role_assignment_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


