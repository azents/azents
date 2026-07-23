# RuntimeProviderAuthenticationBindingRotateRequest

Rotate issued-token enrollment authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_admin_version** | **int** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_rotate_request import RuntimeProviderAuthenticationBindingRotateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingRotateRequest from a JSON string
runtime_provider_authentication_binding_rotate_request_instance = RuntimeProviderAuthenticationBindingRotateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingRotateRequest.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_rotate_request_dict = runtime_provider_authentication_binding_rotate_request_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingRotateRequest from a dict
runtime_provider_authentication_binding_rotate_request_from_dict = RuntimeProviderAuthenticationBindingRotateRequest.from_dict(runtime_provider_authentication_binding_rotate_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


