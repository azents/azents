# SystemAdminMeResponse

Current system administrator response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**user_id** | **str** | Current User ID | 
**roles** | [**List[SystemUserRole]**](SystemUserRole.md) | Current system roles | 

## Example

```python
from azentsadminclient.models.system_admin_me_response import SystemAdminMeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemAdminMeResponse from a JSON string
system_admin_me_response_instance = SystemAdminMeResponse.from_json(json)
# print the JSON string representation of the object
print(SystemAdminMeResponse.to_json())

# convert the object into a dict
system_admin_me_response_dict = system_admin_me_response_instance.to_dict()
# create an instance of SystemAdminMeResponse from a dict
system_admin_me_response_from_dict = SystemAdminMeResponse.from_dict(system_admin_me_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


