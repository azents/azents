# ArchiveRetentionPreviewRequest

Proposed archive retention value for impact preview.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**archived_session_retention_days** | **int** |  | 

## Example

```python
from azentsadminclient.models.archive_retention_preview_request import ArchiveRetentionPreviewRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ArchiveRetentionPreviewRequest from a JSON string
archive_retention_preview_request_instance = ArchiveRetentionPreviewRequest.from_json(json)
# print the JSON string representation of the object
print(ArchiveRetentionPreviewRequest.to_json())

# convert the object into a dict
archive_retention_preview_request_dict = archive_retention_preview_request_instance.to_dict()
# create an instance of ArchiveRetentionPreviewRequest from a dict
archive_retention_preview_request_from_dict = ArchiveRetentionPreviewRequest.from_dict(archive_retention_preview_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


