# SystemSettingVersionConflictDetail

Stable optimistic-mutation conflict detail.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**message** | **str** |  | 
**current_version** | **int** |  | 

## Example

```python
from azentsadminclient.models.system_setting_version_conflict_detail import SystemSettingVersionConflictDetail

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingVersionConflictDetail from a JSON string
system_setting_version_conflict_detail_instance = SystemSettingVersionConflictDetail.from_json(json)
# print the JSON string representation of the object
print(SystemSettingVersionConflictDetail.to_json())

# convert the object into a dict
system_setting_version_conflict_detail_dict = system_setting_version_conflict_detail_instance.to_dict()
# create an instance of SystemSettingVersionConflictDetail from a dict
system_setting_version_conflict_detail_from_dict = SystemSettingVersionConflictDetail.from_dict(system_setting_version_conflict_detail_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


