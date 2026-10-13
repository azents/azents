# GoogleApplicationDetail

Admin redacted effective fields and optimistic version, never secret values.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** |  | 
**client_id** | **str** |  | 
**callback_url** | **str** |  | 
**preview_verified** | **bool** |  | 
**service_access_verified** | **bool** |  | 
**section** | **str** |  | 
**schema_version** | **int** |  | 
**admin_version** | **int** |  | 
**client_id_source** | [**SystemSettingFieldSource**](SystemSettingFieldSource.md) |  | 
**client_secret_source** | [**SystemSettingFieldSource**](SystemSettingFieldSource.md) |  | 
**client_secret_configured** | **bool** |  | 

## Example

```python
from azentsadminclient.models.google_application_detail import GoogleApplicationDetail

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleApplicationDetail from a JSON string
google_application_detail_instance = GoogleApplicationDetail.from_json(json)
# print the JSON string representation of the object
print(GoogleApplicationDetail.to_json())

# convert the object into a dict
google_application_detail_dict = google_application_detail_instance.to_dict()
# create an instance of GoogleApplicationDetail from a dict
google_application_detail_from_dict = GoogleApplicationDetail.from_dict(google_application_detail_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


