# SystemBootstrapFirstAdminRequest

Initial system administrator credentials.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **str** | Initial administrator email | 
**password** | **str** | Initial administrator password | 

## Example

```python
from azentsadminclient.models.system_bootstrap_first_admin_request import SystemBootstrapFirstAdminRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SystemBootstrapFirstAdminRequest from a JSON string
system_bootstrap_first_admin_request_instance = SystemBootstrapFirstAdminRequest.from_json(json)
# print the JSON string representation of the object
print(SystemBootstrapFirstAdminRequest.to_json())

# convert the object into a dict
system_bootstrap_first_admin_request_dict = system_bootstrap_first_admin_request_instance.to_dict()
# create an instance of SystemBootstrapFirstAdminRequest from a dict
system_bootstrap_first_admin_request_from_dict = SystemBootstrapFirstAdminRequest.from_dict(system_bootstrap_first_admin_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


