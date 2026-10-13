# GoogleApplicationPatchRequest

Partial local preparation with explicit secret replace/clear actions.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**client_id** | **str** |  | [optional] 
**client_secret** | [**SystemSettingSecretActionRequest**](SystemSettingSecretActionRequest.md) |  | [optional] 

## Example

```python
from azentsadminclient.models.google_application_patch_request import GoogleApplicationPatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleApplicationPatchRequest from a JSON string
google_application_patch_request_instance = GoogleApplicationPatchRequest.from_json(json)
# print the JSON string representation of the object
print(GoogleApplicationPatchRequest.to_json())

# convert the object into a dict
google_application_patch_request_dict = google_application_patch_request_instance.to_dict()
# create an instance of GoogleApplicationPatchRequest from a dict
google_application_patch_request_from_dict = GoogleApplicationPatchRequest.from_dict(google_application_patch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


