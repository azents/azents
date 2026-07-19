# ArchiveRetentionPreviewResponse

Existing archive impact preview response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**affected_count** | **int** |  | 
**immediately_eligible_count** | **int** |  | 
**cancelled_count** | **int** |  | 
**scheduled_count** | **int** |  | 
**excluded_count** | **int** |  | 

## Example

```python
from azentsadminclient.models.archive_retention_preview_response import ArchiveRetentionPreviewResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ArchiveRetentionPreviewResponse from a JSON string
archive_retention_preview_response_instance = ArchiveRetentionPreviewResponse.from_json(json)
# print the JSON string representation of the object
print(ArchiveRetentionPreviewResponse.to_json())

# convert the object into a dict
archive_retention_preview_response_dict = archive_retention_preview_response_instance.to_dict()
# create an instance of ArchiveRetentionPreviewResponse from a dict
archive_retention_preview_response_from_dict = ArchiveRetentionPreviewResponse.from_dict(archive_retention_preview_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


