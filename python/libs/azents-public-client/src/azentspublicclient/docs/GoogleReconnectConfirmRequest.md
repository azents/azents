# GoogleReconnectConfirmRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**settings** | [**GoogleReconnectSettings**](GoogleReconnectSettings.md) |  | 

## Example

```python
from azentspublicclient.models.google_reconnect_confirm_request import GoogleReconnectConfirmRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleReconnectConfirmRequest from a JSON string
google_reconnect_confirm_request_instance = GoogleReconnectConfirmRequest.from_json(json)
# print the JSON string representation of the object
print(GoogleReconnectConfirmRequest.to_json())

# convert the object into a dict
google_reconnect_confirm_request_dict = google_reconnect_confirm_request_instance.to_dict()
# create an instance of GoogleReconnectConfirmRequest from a dict
google_reconnect_confirm_request_from_dict = GoogleReconnectConfirmRequest.from_dict(google_reconnect_confirm_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


