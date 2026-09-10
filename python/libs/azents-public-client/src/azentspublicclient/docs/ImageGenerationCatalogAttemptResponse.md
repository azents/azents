# ImageGenerationCatalogAttemptResponse

Latest image-generation catalog synchronization attempt response.

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
from azentspublicclient.models.image_generation_catalog_attempt_response import ImageGenerationCatalogAttemptResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ImageGenerationCatalogAttemptResponse from a JSON string
image_generation_catalog_attempt_response_instance = ImageGenerationCatalogAttemptResponse.from_json(json)
# print the JSON string representation of the object
print(ImageGenerationCatalogAttemptResponse.to_json())

# convert the object into a dict
image_generation_catalog_attempt_response_dict = image_generation_catalog_attempt_response_instance.to_dict()
# create an instance of ImageGenerationCatalogAttemptResponse from a dict
image_generation_catalog_attempt_response_from_dict = ImageGenerationCatalogAttemptResponse.from_dict(image_generation_catalog_attempt_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


