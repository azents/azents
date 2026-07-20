# SystemSettingAuditEventResponse

Metadata-only System Settings audit event.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**section** | **str** |  |
**event_type** | [**SystemSettingAuditEventType**](SystemSettingAuditEventType.md) |  |
**source** | [**SystemSettingAuditSource**](SystemSettingAuditSource.md) |  |
**previous_version** | **int** |  |
**new_version** | **int** |  |
**actor_user_id** | **str** |  |
**changed_fields** | **List[str]** |  |
**secret_actions** | **Dict[str, str]** |  |
**validation_status** | [**SystemSettingValidationStatus**](SystemSettingValidationStatus.md) |  |
**candidate_id** | **str** |  |
**impact_confirmed** | **bool** |  |
**confirmation_action** | **str** |  |
**metadata** | **Dict[str, object]** |  |
**created_at** | **datetime** |  |

## Example

```python
from azentsadminclient.models.system_setting_audit_event_response import SystemSettingAuditEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingAuditEventResponse from a JSON string
system_setting_audit_event_response_instance = SystemSettingAuditEventResponse.from_json(json)
# print the JSON string representation of the object
print(SystemSettingAuditEventResponse.to_json())

# convert the object into a dict
system_setting_audit_event_response_dict = system_setting_audit_event_response_instance.to_dict()
# create an instance of SystemSettingAuditEventResponse from a dict
system_setting_audit_event_response_from_dict = SystemSettingAuditEventResponse.from_dict(system_setting_audit_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
