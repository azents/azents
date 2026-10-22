# GoogleReview

Actual grant and reviewed intent remain separate, with no token projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**attempt_id** | **str** |  | 
**expires_at** | **datetime** |  | 
**identity** | [**GoogleIdentity**](GoogleIdentity.md) |  | 
**client_id** | **str** |  | 
**ownership** | **str** |  | 
**reconnect_toolkit_id** | **str** |  | 
**services** | [**List[GoogleService]**](GoogleService.md) |  | 
**tool_groups** | [**List[GoogleToolGroup]**](GoogleToolGroup.md) |  | 
**oauth_request_scopes** | **List[str]** |  | 
**granted_scopes** | **List[str]** |  | 
**timeout** | **float** |  | 
**accesses** | [**List[GoogleServiceAccess]**](GoogleServiceAccess.md) |  | 
**drive_access** | [**GoogleDriveAccess**](GoogleDriveAccess.md) |  | 
**grant_result** | **str** | Receipt evidence for requested Workspace scopes, not an action ceiling. Actual supported tools and Drive extent are projected independently. | 
**renewable** | **bool** |  | 
**can_confirm** | **bool** |  | 
**service_access_verified** | **bool** | Scope review does not verify live resource access. | 

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


