# GooglePickerTokenOutput

Transient manager-browser bearer receipt, never an Agent/model response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**access_token** | **str** |  | 
**expires_at** | **datetime** |  | 
**api_key** | **str** |  | 
**app_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.google_picker_token_output import GooglePickerTokenOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GooglePickerTokenOutput from a JSON string
google_picker_token_output_instance = GooglePickerTokenOutput.from_json(json)
# print the JSON string representation of the object
print(GooglePickerTokenOutput.to_json())

# convert the object into a dict
google_picker_token_output_dict = google_picker_token_output_instance.to_dict()
# create an instance of GooglePickerTokenOutput from a dict
google_picker_token_output_from_dict = GooglePickerTokenOutput.from_dict(google_picker_token_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


