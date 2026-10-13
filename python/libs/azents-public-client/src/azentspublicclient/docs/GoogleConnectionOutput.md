# GoogleConnectionOutput

Saved identity, authorization and selected work under manager authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_id** | **str** |  | 
**status** | **str** |  | 
**identity** | [**GoogleIdentity**](GoogleIdentity.md) |  | 
**selected_tasks** | [**List[GoogleTask]**](GoogleTask.md) |  | 
**timeout** | **float** |  | 
**tasks** | [**List[GoogleTaskAccess]**](GoogleTaskAccess.md) |  | 
**renewable** | **bool** |  | 
**service_access_verified** | **bool** |  | 

## Example

```python
from azentspublicclient.models.google_connection_output import GoogleConnectionOutput

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleConnectionOutput from a JSON string
google_connection_output_instance = GoogleConnectionOutput.from_json(json)
# print the JSON string representation of the object
print(GoogleConnectionOutput.to_json())

# convert the object into a dict
google_connection_output_dict = google_connection_output_instance.to_dict()
# create an instance of GoogleConnectionOutput from a dict
google_connection_output_from_dict = GoogleConnectionOutput.from_dict(google_connection_output_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


