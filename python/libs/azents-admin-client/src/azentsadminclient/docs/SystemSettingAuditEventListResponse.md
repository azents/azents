# SystemSettingAuditEventListResponse

Paginated metadata-only System Settings audit events.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SystemSettingAuditEventResponse]**](SystemSettingAuditEventResponse.md) |  |
**total** | **int** |  |

## Example

```python
from azentsadminclient.models.system_setting_audit_event_list_response import SystemSettingAuditEventListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingAuditEventListResponse from a JSON string
system_setting_audit_event_list_response_instance = SystemSettingAuditEventListResponse.from_json(json)
# print the JSON string representation of the object
print(SystemSettingAuditEventListResponse.to_json())

# convert the object into a dict
system_setting_audit_event_list_response_dict = system_setting_audit_event_list_response_instance.to_dict()
# create an instance of SystemSettingAuditEventListResponse from a dict
system_setting_audit_event_list_response_from_dict = SystemSettingAuditEventListResponse.from_dict(system_setting_audit_event_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
