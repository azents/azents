# GoogleConfirmRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**settings** | [**GoogleFinalSettings**](GoogleFinalSettings.md) |  | 

## Example

```python
from azentspublicclient.models.google_confirm_request import GoogleConfirmRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleConfirmRequest from a JSON string
google_confirm_request_instance = GoogleConfirmRequest.from_json(json)
# print the JSON string representation of the object
print(GoogleConfirmRequest.to_json())

# convert the object into a dict
google_confirm_request_dict = google_confirm_request_instance.to_dict()
# create an instance of GoogleConfirmRequest from a dict
google_confirm_request_from_dict = GoogleConfirmRequest.from_dict(google_confirm_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


