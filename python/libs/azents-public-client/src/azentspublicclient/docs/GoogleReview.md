# GoogleReview

Actual grant result with token-free exact ownership/capability projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 
**expires_at** | **datetime** |  | 
**identity** | [**GoogleIdentity**](GoogleIdentity.md) |  | 
**client_id** | **str** |  | 
**ownership** | **str** |  | 
**reconnect_toolkit_id** | **str** |  | 
**requested_tasks** | [**List[GoogleTask]**](GoogleTask.md) |  | 
**timeout** | **float** |  | 
**tasks** | [**List[GoogleTaskAccess]**](GoogleTaskAccess.md) |  | 
**grant_result** | **str** |  | 
**renewable** | **bool** |  | 
**can_confirm** | **bool** |  | 
**service_access_verified** | **bool** | Scope review does not verify live resource access. | 
**security_notice** | **str** |  | 

## Example

```python
from azentspublicclient.models.google_review import GoogleReview

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleReview from a JSON string
google_review_instance = GoogleReview.from_json(json)
# print the JSON string representation of the object
print(GoogleReview.to_json())

# convert the object into a dict
google_review_dict = google_review_instance.to_dict()
# create an instance of GoogleReview from a dict
google_review_from_dict = GoogleReview.from_dict(google_review_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


