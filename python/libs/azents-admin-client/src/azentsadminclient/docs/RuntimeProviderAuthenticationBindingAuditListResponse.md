# RuntimeProviderAuthenticationBindingAuditListResponse

Binding audit history response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeProviderAuthenticationBindingAuditEventResponse]**](RuntimeProviderAuthenticationBindingAuditEventResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_audit_list_response import RuntimeProviderAuthenticationBindingAuditListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingAuditListResponse from a JSON string
runtime_provider_authentication_binding_audit_list_response_instance = RuntimeProviderAuthenticationBindingAuditListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingAuditListResponse.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_audit_list_response_dict = runtime_provider_authentication_binding_audit_list_response_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingAuditListResponse from a dict
runtime_provider_authentication_binding_audit_list_response_from_dict = RuntimeProviderAuthenticationBindingAuditListResponse.from_dict(runtime_provider_authentication_binding_audit_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


