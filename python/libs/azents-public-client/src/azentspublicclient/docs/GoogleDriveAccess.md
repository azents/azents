# GoogleDriveAccess

Scope extent only; Google retains resource eligibility and ACL authority.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**whole_metadata_read** | **bool** |  | 
**whole_content_read** | **bool** |  | 
**whole_content_write** | **bool** |  | 
**whole_metadata_write** | **bool** |  | 
**app_file_read** | **bool** |  | 
**app_file_write** | **bool** |  | 

## Example

```python
from azentspublicclient.models.google_drive_access import GoogleDriveAccess

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleDriveAccess from a JSON string
google_drive_access_instance = GoogleDriveAccess.from_json(json)
# print the JSON string representation of the object
print(GoogleDriveAccess.to_json())

# convert the object into a dict
google_drive_access_dict = google_drive_access_instance.to_dict()
# create an instance of GoogleDriveAccess from a dict
google_drive_access_from_dict = GoogleDriveAccess.from_dict(google_drive_access_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


