# SystemModelCatalogSyncAttemptResponse

Latest model catalog sync attempt response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
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
from azentsadminclient.models.system_model_catalog_sync_attempt_response import SystemModelCatalogSyncAttemptResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemModelCatalogSyncAttemptResponse from a JSON string
system_model_catalog_sync_attempt_response_instance = SystemModelCatalogSyncAttemptResponse.from_json(json)
# print the JSON string representation of the object
print(SystemModelCatalogSyncAttemptResponse.to_json())

# convert the object into a dict
system_model_catalog_sync_attempt_response_dict = system_model_catalog_sync_attempt_response_instance.to_dict()
# create an instance of SystemModelCatalogSyncAttemptResponse from a dict
system_model_catalog_sync_attempt_response_from_dict = SystemModelCatalogSyncAttemptResponse.from_dict(system_model_catalog_sync_attempt_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


