# GoogleConnectInput

Explicit work selection before initial or ordinary reconnect authorization.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tasks** | [**List[GoogleTask]**](GoogleTask.md) |  | 
**timeout** | **float** |  | 

## Example

```python
from azentspublicclient.models.google_connect_input import GoogleConnectInput

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleConnectInput from a JSON string
google_connect_input_instance = GoogleConnectInput.from_json(json)
# print the JSON string representation of the object
print(GoogleConnectInput.to_json())

# convert the object into a dict
google_connect_input_dict = google_connect_input_instance.to_dict()
# create an instance of GoogleConnectInput from a dict
google_connect_input_from_dict = GoogleConnectInput.from_dict(google_connect_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


