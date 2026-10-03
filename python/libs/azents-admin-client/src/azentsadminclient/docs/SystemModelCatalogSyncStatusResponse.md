# SystemModelCatalogSyncStatusResponse

Latest operational state, excluding opaque active work ownership.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** |  | 
**started_at** | **datetime** |  | 
**finished_at** | **datetime** |  | 
**failure_code** | **str** |  | 
**failure_message** | **str** |  | 
**action_hint** | **str** |  | 
**fetched_count** | **int** |  | 
**matched_count** | **int** |  | 
**skipped_count** | **int** |  | 
**hidden_count** | **int** |  | 

## Example

```python
from azentsadminclient.models.system_model_catalog_sync_status_response import SystemModelCatalogSyncStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemModelCatalogSyncStatusResponse from a JSON string
system_model_catalog_sync_status_response_instance = SystemModelCatalogSyncStatusResponse.from_json(json)
# print the JSON string representation of the object
print(SystemModelCatalogSyncStatusResponse.to_json())

# convert the object into a dict
system_model_catalog_sync_status_response_dict = system_model_catalog_sync_status_response_instance.to_dict()
# create an instance of SystemModelCatalogSyncStatusResponse from a dict
system_model_catalog_sync_status_response_from_dict = SystemModelCatalogSyncStatusResponse.from_dict(system_model_catalog_sync_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


