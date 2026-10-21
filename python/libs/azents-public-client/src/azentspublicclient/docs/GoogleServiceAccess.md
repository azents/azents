# GoogleServiceAccess

Local enablement and actual operation evidence are independent facts.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**service** | [**GoogleService**](GoogleService.md) |  | 
**enabled** | **bool** |  | 
**status** | **str** |  | 
**permitted_tools** | [**List[GoogleWorkspaceOperation]**](GoogleWorkspaceOperation.md) |  | 
**unavailable_tools** | [**List[GoogleWorkspaceOperation]**](GoogleWorkspaceOperation.md) |  | 

## Example

```python
from azentspublicclient.models.google_service_access import GoogleServiceAccess

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleServiceAccess from a JSON string
google_service_access_instance = GoogleServiceAccess.from_json(json)
# print the JSON string representation of the object
print(GoogleServiceAccess.to_json())

# convert the object into a dict
google_service_access_dict = google_service_access_instance.to_dict()
# create an instance of GoogleServiceAccess from a dict
google_service_access_from_dict = GoogleServiceAccess.from_dict(google_service_access_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


