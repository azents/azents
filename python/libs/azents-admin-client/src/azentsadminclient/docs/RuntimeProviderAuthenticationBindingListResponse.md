# RuntimeProviderAuthenticationBindingListResponse

Provider-scoped authentication binding inventory.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeProviderAuthenticationBindingResponse]**](RuntimeProviderAuthenticationBindingResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_list_response import RuntimeProviderAuthenticationBindingListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingListResponse from a JSON string
runtime_provider_authentication_binding_list_response_instance = RuntimeProviderAuthenticationBindingListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingListResponse.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_list_response_dict = runtime_provider_authentication_binding_list_response_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingListResponse from a dict
runtime_provider_authentication_binding_list_response_from_dict = RuntimeProviderAuthenticationBindingListResponse.from_dict(runtime_provider_authentication_binding_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


