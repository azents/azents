# GoogleMetadataEdits

Explicit settings-apply intent; ordinary recovery omits this payload.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_revision** | **int** |  | 
**name** | **str** |  | 
**slug** | **str** |  | 
**description** | **str** |  | 
**prompt** | **str** |  | 
**enabled** | **bool** |  | 
**always_expose_tools** | **bool** |  | 

## Example

```python
from azentspublicclient.models.google_metadata_edits import GoogleMetadataEdits

# TODO update the JSON string below
json = "{}"
# create an instance of GoogleMetadataEdits from a JSON string
google_metadata_edits_instance = GoogleMetadataEdits.from_json(json)
# print the JSON string representation of the object
print(GoogleMetadataEdits.to_json())

# convert the object into a dict
google_metadata_edits_dict = google_metadata_edits_instance.to_dict()
# create an instance of GoogleMetadataEdits from a dict
google_metadata_edits_from_dict = GoogleMetadataEdits.from_dict(google_metadata_edits_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


