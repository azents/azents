# GoogleConnectOutput

Browser navigation receipt, not a saved/executable connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 
**authorization_url** | **str** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.google_connect_output import GoogleConnectOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleConnectOutput from a JSON string
google_connect_output_instance = GoogleConnectOutput.from_json(json)
# print the JSON string representation of the object
print(GoogleConnectOutput.to_json())

# convert the object into a dict
google_connect_output_dict = google_connect_output_instance.to_dict()
# create an instance of GoogleConnectOutput from a dict
google_connect_output_from_dict = GoogleConnectOutput.from_dict(google_connect_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


