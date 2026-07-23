# RuntimeProviderAuthenticationBindingResponse

Secret-safe Provider authentication binding.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_id** | **str** |  | 
**auth_method** | [**RuntimeProviderAuthMethod**](RuntimeProviderAuthMethod.md) |  | 
**subject** | **str** |  | 
**state** | [**RuntimeProviderBindingState**](RuntimeProviderBindingState.md) |  | 
**owner** | [**RuntimeProviderBindingOwner**](RuntimeProviderBindingOwner.md) |  | 
**bootstrap_declaration_id** | **str** |  | 
**config** | **Dict[str, object]** |  | 
**admin_version** | **int** |  | 
**connected** | **bool** |  | 
**last_authenticated_at** | **datetime** |  | 
**last_connected_at** | **datetime** |  | 
**revoked_at** | **datetime** |  | 
**revoked_by_user_id** | **str** |  | 
**revocation_reason** | **str** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_response import RuntimeProviderAuthenticationBindingResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingResponse from a JSON string
runtime_provider_authentication_binding_response_instance = RuntimeProviderAuthenticationBindingResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingResponse.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_response_dict = runtime_provider_authentication_binding_response_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingResponse from a dict
runtime_provider_authentication_binding_response_from_dict = RuntimeProviderAuthenticationBindingResponse.from_dict(runtime_provider_authentication_binding_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


