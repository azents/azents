# GoogleTaskAccess

Task-level permission evidence; no live resource-access promise.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**task** | [**GoogleTask**](GoogleTask.md) |  | 
**service** | [**GoogleService**](GoogleService.md) |  | 
**status** | **str** |  | 
**permitted_tools** | **List[str]** |  | 
**unavailable_tools** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.google_task_access import GoogleTaskAccess

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleTaskAccess from a JSON string
google_task_access_instance = GoogleTaskAccess.from_json(json)
# print the JSON string representation of the object
print(GoogleTaskAccess.to_json())

# convert the object into a dict
google_task_access_dict = google_task_access_instance.to_dict()
# create an instance of GoogleTaskAccess from a dict
google_task_access_from_dict = GoogleTaskAccess.from_dict(google_task_access_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


