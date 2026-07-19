# FileLifecycleSettingsResponse

Instance-wide file lifecycle settings response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**archived_session_retention_days** | **int** |  | 
**revision** | **int** | Optimistic settings revision | 
**updated_by_user_id** | **str** |  | 
**created_at** | **datetime** | Created timestamp | 
**updated_at** | **datetime** | Updated timestamp | 
**active_application** | [**ArchiveRetentionApplicationResponse**](ArchiveRetentionApplicationResponse.md) |  | 

## Example

```python
from azentsadminclient.models.file_lifecycle_settings_response import FileLifecycleSettingsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of FileLifecycleSettingsResponse from a JSON string
file_lifecycle_settings_response_instance = FileLifecycleSettingsResponse.from_json(json)
# print the JSON string representation of the object
print(FileLifecycleSettingsResponse.to_json())

# convert the object into a dict
file_lifecycle_settings_response_dict = file_lifecycle_settings_response_instance.to_dict()
# create an instance of FileLifecycleSettingsResponse from a dict
file_lifecycle_settings_response_from_dict = FileLifecycleSettingsResponse.from_dict(file_lifecycle_settings_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


