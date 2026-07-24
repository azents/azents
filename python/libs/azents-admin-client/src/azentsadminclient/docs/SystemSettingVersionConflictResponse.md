# SystemSettingVersionConflictResponse

FastAPI error envelope for an optimistic System Settings conflict.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**detail** | [**SystemSettingVersionConflictDetail**](SystemSettingVersionConflictDetail.md) |  | 

## Example

```python
from azentsadminclient.models.system_setting_version_conflict_response import SystemSettingVersionConflictResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingVersionConflictResponse from a JSON string
system_setting_version_conflict_response_instance = SystemSettingVersionConflictResponse.from_json(json)
# print the JSON string representation of the object
print(SystemSettingVersionConflictResponse.to_json())

# convert the object into a dict
system_setting_version_conflict_response_dict = system_setting_version_conflict_response_instance.to_dict()
# create an instance of SystemSettingVersionConflictResponse from a dict
system_setting_version_conflict_response_from_dict = SystemSettingVersionConflictResponse.from_dict(system_setting_version_conflict_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


