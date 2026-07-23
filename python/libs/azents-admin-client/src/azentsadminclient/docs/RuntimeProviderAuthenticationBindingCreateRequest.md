# RuntimeProviderAuthenticationBindingCreateRequest

Create one Admin-owned Provider authentication binding.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**auth_method** | [**RuntimeProviderAuthMethod**](RuntimeProviderAuthMethod.md) |  | 
**subject** | **str** |  | 
**config** | **Dict[str, object]** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_create_request import RuntimeProviderAuthenticationBindingCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingCreateRequest from a JSON string
runtime_provider_authentication_binding_create_request_instance = RuntimeProviderAuthenticationBindingCreateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingCreateRequest.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_create_request_dict = runtime_provider_authentication_binding_create_request_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingCreateRequest from a dict
runtime_provider_authentication_binding_create_request_from_dict = RuntimeProviderAuthenticationBindingCreateRequest.from_dict(runtime_provider_authentication_binding_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


