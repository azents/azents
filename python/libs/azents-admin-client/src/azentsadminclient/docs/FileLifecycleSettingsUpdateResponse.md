# FileLifecycleSettingsUpdateResponse

Updated settings and optional durable recalculation application.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**settings** | [**FileLifecycleSettingsResponse**](FileLifecycleSettingsResponse.md) |  | 
**application** | [**ArchiveRetentionApplicationResponse**](ArchiveRetentionApplicationResponse.md) |  | 

## Example

```python
from azentsadminclient.models.file_lifecycle_settings_update_response import FileLifecycleSettingsUpdateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of FileLifecycleSettingsUpdateResponse from a JSON string
file_lifecycle_settings_update_response_instance = FileLifecycleSettingsUpdateResponse.from_json(json)
# print the JSON string representation of the object
print(FileLifecycleSettingsUpdateResponse.to_json())

# convert the object into a dict
file_lifecycle_settings_update_response_dict = file_lifecycle_settings_update_response_instance.to_dict()
# create an instance of FileLifecycleSettingsUpdateResponse from a dict
file_lifecycle_settings_update_response_from_dict = FileLifecycleSettingsUpdateResponse.from_dict(file_lifecycle_settings_update_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


