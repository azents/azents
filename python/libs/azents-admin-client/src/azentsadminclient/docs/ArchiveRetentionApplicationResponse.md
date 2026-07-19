# ArchiveRetentionApplicationResponse

Durable existing-archive recalculation progress response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**target_revision** | **int** |  | 
**target_retention_days** | **int** |  | 
**requested_by_user_id** | **str** |  | 
**status** | [**ArchivedSessionRetentionApplicationStatus**](ArchivedSessionRetentionApplicationStatus.md) |  | 
**cursor_session_id** | **str** |  | 
**affected_count** | **int** |  | 
**immediately_eligible_count** | **int** |  | 
**cancelled_count** | **int** |  | 
**scheduled_count** | **int** |  | 
**skipped_count** | **int** |  | 
**attempt_count** | **int** |  | 
**lease_owner** | **str** |  | 
**lease_until** | **datetime** |  | 
**next_attempt_at** | **datetime** |  | 
**last_error_kind** | **str** |  | 
**last_error_summary** | **str** |  | 
**started_at** | **datetime** |  | 
**completed_at** | **datetime** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.archive_retention_application_response import ArchiveRetentionApplicationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ArchiveRetentionApplicationResponse from a JSON string
archive_retention_application_response_instance = ArchiveRetentionApplicationResponse.from_json(json)
# print the JSON string representation of the object
print(ArchiveRetentionApplicationResponse.to_json())

# convert the object into a dict
archive_retention_application_response_dict = archive_retention_application_response_instance.to_dict()
# create an instance of ArchiveRetentionApplicationResponse from a dict
archive_retention_application_response_from_dict = ArchiveRetentionApplicationResponse.from_dict(archive_retention_application_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


