# GooglePreparation

Separate local OAuth and optional Picker preparation, without live claims.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** |  | 
**client_id** | **str** |  | 
**callback_url** | **str** |  | 
**picker_status** | **str** |  | 
**service_access_verified** | **bool** | Local preparation does not verify live service access. | 

## Example

```python
from azentspublicclient.models.google_preparation import GooglePreparation

# TODO update the JSON string below
json = "{}"
# create an instance of GooglePreparation from a JSON string
google_preparation_instance = GooglePreparation.from_json(json)
# print the JSON string representation of the object
print(GooglePreparation.to_json())

# convert the object into a dict
google_preparation_dict = google_preparation_instance.to_dict()
# create an instance of GooglePreparation from a dict
google_preparation_from_dict = GooglePreparation.from_dict(google_preparation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


