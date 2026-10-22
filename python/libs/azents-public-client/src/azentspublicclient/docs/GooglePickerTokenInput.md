# GooglePickerTokenInput

Only the expected current target is accepted; scope/token inputs are closed.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**connection_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.google_picker_token_input import GooglePickerTokenInput

# TODO update the JSON string below
json = "{}"
# create an instance of GooglePickerTokenInput from a JSON string
google_picker_token_input_instance = GooglePickerTokenInput.from_json(json)
# print the JSON string representation of the object
print(GooglePickerTokenInput.to_json())

# convert the object into a dict
google_picker_token_input_dict = google_picker_token_input_instance.to_dict()
# create an instance of GooglePickerTokenInput from a dict
google_picker_token_input_from_dict = GooglePickerTokenInput.from_dict(google_picker_token_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


