# SystemSettingSecretActionRequest

Explicit secret replacement or clearing action.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**action** | [**SystemSettingSecretActionType**](SystemSettingSecretActionType.md) |  |
**value** | **str** |  | [optional]

## Example

```python
from azentsadminclient.models.system_setting_secret_action_request import SystemSettingSecretActionRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingSecretActionRequest from a JSON string
system_setting_secret_action_request_instance = SystemSettingSecretActionRequest.from_json(json)
# print the JSON string representation of the object
print(SystemSettingSecretActionRequest.to_json())

# convert the object into a dict
system_setting_secret_action_request_dict = system_setting_secret_action_request_instance.to_dict()
# create an instance of SystemSettingSecretActionRequest from a dict
system_setting_secret_action_request_from_dict = SystemSettingSecretActionRequest.from_dict(system_setting_secret_action_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
