# ExternalChannelResponseModeSetting

Canonical full-value External Channel response-mode setting.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**response_mode** | [**ExternalChannelResponseMode**](ExternalChannelResponseMode.md) |  | 

## Example

```python
from azentspublicclient.models.external_channel_response_mode_setting import ExternalChannelResponseModeSetting

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelResponseModeSetting from a JSON string
external_channel_response_mode_setting_instance = ExternalChannelResponseModeSetting.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelResponseModeSetting.to_json())

# convert the object into a dict
external_channel_response_mode_setting_dict = external_channel_response_mode_setting_instance.to_dict()
# create an instance of ExternalChannelResponseModeSetting from a dict
external_channel_response_mode_setting_from_dict = ExternalChannelResponseModeSetting.from_dict(external_channel_response_mode_setting_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


