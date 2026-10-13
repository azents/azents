# CompactedEventRetentionSettingsResponse

Lifecycle settings after an independent compacted-event policy mutation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**archived_session_retention_days** | **int** |  | 
**revision** | **int** | Optimistic settings revision | 
**compacted_event_retention_days** | **int** |  | 
**updated_by_user_id** | **str** |  | 
**created_at** | **datetime** | Created timestamp | 
**updated_at** | **datetime** | Updated timestamp | 

## Example

```python
from azentsadminclient.models.compacted_event_retention_settings_response import CompactedEventRetentionSettingsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of CompactedEventRetentionSettingsResponse from a JSON string
compacted_event_retention_settings_response_instance = CompactedEventRetentionSettingsResponse.from_json(json)
# print the JSON string representation of the object
print(CompactedEventRetentionSettingsResponse.to_json())

# convert the object into a dict
compacted_event_retention_settings_response_dict = compacted_event_retention_settings_response_instance.to_dict()
# create an instance of CompactedEventRetentionSettingsResponse from a dict
compacted_event_retention_settings_response_from_dict = CompactedEventRetentionSettingsResponse.from_dict(compacted_event_retention_settings_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


