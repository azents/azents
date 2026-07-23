# RuntimeProviderAuthenticationBindingRevokeRequest

Revoke a binding using optimistic concurrency.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_admin_version** | **int** |  | 
**reason** | **str** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_revoke_request import RuntimeProviderAuthenticationBindingRevokeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingRevokeRequest from a JSON string
runtime_provider_authentication_binding_revoke_request_instance = RuntimeProviderAuthenticationBindingRevokeRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingRevokeRequest.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_revoke_request_dict = runtime_provider_authentication_binding_revoke_request_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingRevokeRequest from a dict
runtime_provider_authentication_binding_revoke_request_from_dict = RuntimeProviderAuthenticationBindingRevokeRequest.from_dict(runtime_provider_authentication_binding_revoke_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


