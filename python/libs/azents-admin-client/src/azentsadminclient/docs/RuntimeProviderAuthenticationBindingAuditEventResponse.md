# RuntimeProviderAuthenticationBindingAuditEventResponse

Metadata-only binding audit event.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**binding_id** | **str** |  | 
**event_type** | [**RuntimeProviderBindingAuditEventType**](RuntimeProviderBindingAuditEventType.md) |  | 
**actor_user_id** | **str** |  | 
**previous_admin_version** | **int** |  | 
**new_admin_version** | **int** |  | 
**metadata** | **Dict[str, object]** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_authentication_binding_audit_event_response import RuntimeProviderAuthenticationBindingAuditEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAuthenticationBindingAuditEventResponse from a JSON string
runtime_provider_authentication_binding_audit_event_response_instance = RuntimeProviderAuthenticationBindingAuditEventResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAuthenticationBindingAuditEventResponse.to_json())

# convert the object into a dict
runtime_provider_authentication_binding_audit_event_response_dict = runtime_provider_authentication_binding_audit_event_response_instance.to_dict()
# create an instance of RuntimeProviderAuthenticationBindingAuditEventResponse from a dict
runtime_provider_authentication_binding_audit_event_response_from_dict = RuntimeProviderAuthenticationBindingAuditEventResponse.from_dict(runtime_provider_authentication_binding_audit_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


