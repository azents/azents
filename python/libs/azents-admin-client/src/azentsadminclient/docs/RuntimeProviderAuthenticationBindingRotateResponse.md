# RuntimeProviderAuthenticationBindingRotateResponse

One-time enrollment secret plus the rotated safe binding.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**binding** | [**RuntimeProviderAuthenticationBindingResponse**](RuntimeProviderAuthenticationBindingResponse.md) |  | 
**grant_id** | **str** |  | 
**secret** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_rotate_response import RuntimeProviderAuthenticationBindingRotateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingRotateResponse from a JSON string
runtime_provider_authentication_binding_rotate_response_instance = RuntimeProviderAuthenticationBindingRotateResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingRotateResponse.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_rotate_response_dict = runtime_provider_authentication_binding_rotate_response_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingRotateResponse from a dict
runtime_provider_authentication_binding_rotate_response_from_dict = RuntimeProviderAuthenticationBindingRotateResponse.from_dict(runtime_provider_authentication_binding_rotate_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


