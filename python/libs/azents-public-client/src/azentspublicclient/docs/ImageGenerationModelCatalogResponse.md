# ImageGenerationModelCatalogResponse

Stored image-generation model availability response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**default_available** | **bool** |  | 
**explicit_selection_supported** | **bool** |  | 
**catalog_id** | **str** |  | 
**snapshot_id** | **str** |  | 
**snapshot_configuration_version** | **int** |  | 
**current_configuration_version** | **int** |  | 
**snapshot_created_at** | **datetime** |  | 
**latest_attempt** | [**ImageGenerationCatalogAttemptResponse**](ImageGenerationCatalogAttemptResponse.md) |  | 
**stale** | **bool** |  | 
**generation_current** | **bool** |  | 
**sync_available_at** | **datetime** |  | 
**automatic_retry_blocked** | **bool** |  | 
**entries** | [**List[ImageGenerationCatalogEntryResponse]**](ImageGenerationCatalogEntryResponse.md) |  | 
**total** | **int** |  | 

## Example

```python
from azentspublicclient.models.image_generation_model_catalog_response import ImageGenerationModelCatalogResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ImageGenerationModelCatalogResponse from a JSON string
image_generation_model_catalog_response_instance = ImageGenerationModelCatalogResponse.from_json(json)
# print the JSON string representation of the object
print(ImageGenerationModelCatalogResponse.to_json())

# convert the object into a dict
image_generation_model_catalog_response_dict = image_generation_model_catalog_response_instance.to_dict()
# create an instance of ImageGenerationModelCatalogResponse from a dict
image_generation_model_catalog_response_from_dict = ImageGenerationModelCatalogResponse.from_dict(image_generation_model_catalog_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


