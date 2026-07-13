# SystemBootstrapFirstAdminResponse

Initial system administrator session response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** | JWT access token |
**refresh_token** | **str** | Refresh token |
**expires_in** | **int** | Access token expiration time in seconds |

## Example

```python
from azentsadminclient.models.system_bootstrap_first_admin_response import SystemBootstrapFirstAdminResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemBootstrapFirstAdminResponse from a JSON string
system_bootstrap_first_admin_response_instance = SystemBootstrapFirstAdminResponse.from_json(json)
# print the JSON string representation of the object
print(SystemBootstrapFirstAdminResponse.to_json())

# convert the object into a dict
system_bootstrap_first_admin_response_dict = system_bootstrap_first_admin_response_instance.to_dict()
# create an instance of SystemBootstrapFirstAdminResponse from a dict
system_bootstrap_first_admin_response_from_dict = SystemBootstrapFirstAdminResponse.from_dict(system_bootstrap_first_admin_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
