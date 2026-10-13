# GoogleReconnectSettings

Reconnect changes authentication selection, not unrelated saved metadata.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tasks** | [**List[GoogleTask]**](GoogleTask.md) |  | 
**timeout** | **float** |  | 
**security_risk_acknowledged** | **bool** |  | 

## Example

```python
from azentspublicclient.models.google_reconnect_settings import GoogleReconnectSettings

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleReconnectSettings from a JSON string
google_reconnect_settings_instance = GoogleReconnectSettings.from_json(json)
# print the JSON string representation of the object
print(GoogleReconnectSettings.to_json())

# convert the object into a dict
google_reconnect_settings_dict = google_reconnect_settings_instance.to_dict()
# create an instance of GoogleReconnectSettings from a dict
google_reconnect_settings_from_dict = GoogleReconnectSettings.from_dict(google_reconnect_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


