# GoogleServicesUpdateInput

Revision-fenced local switch save; empty services is a valid inactive state.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**services** | [**List[GoogleService]**](GoogleService.md) |  | 

## Example

```python
from azentspublicclient.models.google_services_update_input import GoogleServicesUpdateInput

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleServicesUpdateInput from a JSON string
google_services_update_input_instance = GoogleServicesUpdateInput.from_json(json)
# print the JSON string representation of the object
print(GoogleServicesUpdateInput.to_json())

# convert the object into a dict
google_services_update_input_dict = google_services_update_input_instance.to_dict()
# create an instance of GoogleServicesUpdateInput from a dict
google_services_update_input_from_dict = GoogleServicesUpdateInput.from_dict(google_services_update_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


