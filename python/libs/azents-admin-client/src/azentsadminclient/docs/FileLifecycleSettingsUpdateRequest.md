# FileLifecycleSettingsUpdateRequest

Optimistic archive retention settings update.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**archived_session_retention_days** | **int** |  | 
**application_scope** | **str** |  | 

## Example

```python
from azentsadminclient.models.file_lifecycle_settings_update_request import FileLifecycleSettingsUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of FileLifecycleSettingsUpdateRequest from a JSON string
file_lifecycle_settings_update_request_instance = FileLifecycleSettingsUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(FileLifecycleSettingsUpdateRequest.to_json())

# convert the object into a dict
file_lifecycle_settings_update_request_dict = file_lifecycle_settings_update_request_instance.to_dict()
# create an instance of FileLifecycleSettingsUpdateRequest from a dict
file_lifecycle_settings_update_request_from_dict = FileLifecycleSettingsUpdateRequest.from_dict(file_lifecycle_settings_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


