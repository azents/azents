# MySystemRolesResponse

Current User system role response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**roles** | [**List[SystemUserRole]**](SystemUserRole.md) | Current User system roles |

## Example

```python
from azentspublicclient.models.my_system_roles_response import MySystemRolesResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MySystemRolesResponse from a JSON string
my_system_roles_response_instance = MySystemRolesResponse.from_json(json)
# print the JSON string representation of the object
print(MySystemRolesResponse.to_json())

# convert the object into a dict
my_system_roles_response_dict = my_system_roles_response_instance.to_dict()
# create an instance of MySystemRolesResponse from a dict
my_system_roles_response_from_dict = MySystemRolesResponse.from_dict(my_system_roles_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
