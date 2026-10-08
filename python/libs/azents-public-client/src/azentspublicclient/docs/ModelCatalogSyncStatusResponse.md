# ModelCatalogSyncStatusResponse

Current model catalog synchronization response.

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
from azentspublicclient.models.model_catalog_sync_status_response import ModelCatalogSyncStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCatalogSyncStatusResponse from a JSON string
model_catalog_sync_status_response_instance = ModelCatalogSyncStatusResponse.from_json(json)
# print the JSON string representation of the object
print(ModelCatalogSyncStatusResponse.to_json())

# convert the object into a dict
model_catalog_sync_status_response_dict = model_catalog_sync_status_response_instance.to_dict()
# create an instance of ModelCatalogSyncStatusResponse from a dict
model_catalog_sync_status_response_from_dict = ModelCatalogSyncStatusResponse.from_dict(model_catalog_sync_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


