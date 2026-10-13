# GoogleCancelOutput

Publication won the race or candidate was locally abandoned.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**cancelled** | **bool** |  | 
**publication** | [**GooglePublishedOutput**](GooglePublishedOutput.md) |  | 

## Example

```python
from azentspublicclient.models.google_cancel_output import GoogleCancelOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleCancelOutput from a JSON string
google_cancel_output_instance = GoogleCancelOutput.from_json(json)
# print the JSON string representation of the object
print(GoogleCancelOutput.to_json())

# convert the object into a dict
google_cancel_output_dict = google_cancel_output_instance.to_dict()
# create an instance of GoogleCancelOutput from a dict
google_cancel_output_from_dict = GoogleCancelOutput.from_dict(google_cancel_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


