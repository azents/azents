# ImageGenerationCatalogEntryResponse

Stored image-generation catalog entry response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider** | [**LLMProvider**](LLMProvider.md) |  | 
**provider_model_identifier** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**recommendation_rank** | **int** |  | 
**lifecycle_status** | **str** |  | 
**visibility_status** | **str** |  | 
**source_metadata** | **Dict[str, object]** |  | 
**projection_metadata** | **Dict[str, object]** |  | 

## Example

```python
from azentspublicclient.models.image_generation_catalog_entry_response import ImageGenerationCatalogEntryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ImageGenerationCatalogEntryResponse from a JSON string
image_generation_catalog_entry_response_instance = ImageGenerationCatalogEntryResponse.from_json(json)
# print the JSON string representation of the object
print(ImageGenerationCatalogEntryResponse.to_json())

# convert the object into a dict
image_generation_catalog_entry_response_dict = image_generation_catalog_entry_response_instance.to_dict()
# create an instance of ImageGenerationCatalogEntryResponse from a dict
image_generation_catalog_entry_response_from_dict = ImageGenerationCatalogEntryResponse.from_dict(image_generation_catalog_entry_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


