# ImageGenerationCatalogSyncStatusResponse

Current image-generation synchronization response.

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
from azentspublicclient.models.image_generation_catalog_sync_status_response import ImageGenerationCatalogSyncStatusResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ImageGenerationCatalogSyncStatusResponse from a JSON string
image_generation_catalog_sync_status_response_instance = ImageGenerationCatalogSyncStatusResponse.from_json(json)
# print the JSON string representation of the object
print(ImageGenerationCatalogSyncStatusResponse.to_json())

# convert the object into a dict
image_generation_catalog_sync_status_response_dict = image_generation_catalog_sync_status_response_instance.to_dict()
# create an instance of ImageGenerationCatalogSyncStatusResponse from a dict
image_generation_catalog_sync_status_response_from_dict = ImageGenerationCatalogSyncStatusResponse.from_dict(image_generation_catalog_sync_status_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


