# GooglePublishedOutput

Idempotent historical outcome; current binding is not current readiness.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_id** | **str** |  | 
**connection_id** | **str** |  | 
**current** | **bool** |  | 

## Example

```python
from azentspublicclient.models.google_published_output import GooglePublishedOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GooglePublishedOutput from a JSON string
google_published_output_instance = GooglePublishedOutput.from_json(json)
# print the JSON string representation of the object
print(GooglePublishedOutput.to_json())

# convert the object into a dict
google_published_output_dict = google_published_output_instance.to_dict()
# create an instance of GooglePublishedOutput from a dict
google_published_output_from_dict = GooglePublishedOutput.from_dict(google_published_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


