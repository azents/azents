# ModelCatalogEntryResponse

Stored model catalog entry response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**provider** | [**LLMProvider**](LLMProvider.md) |  |
**provider_model_identifier** | **str** |  |
**runtime_model_identifier** | **str** |  |
**display_name** | **str** |  |
**normalized_capabilities** | [**ModelCapabilities**](ModelCapabilities.md) |  |
**lifecycle_status** | **str** |  |
**visibility_status** | **str** |  |
**publisher** | **str** |  |
**family** | **str** |  |
**source_metadata** | **Dict[str, object]** |  |
**projection_metadata** | **Dict[str, object]** |  |

## Example

```python
from azentspublicclient.models.model_catalog_entry_response import ModelCatalogEntryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCatalogEntryResponse from a JSON string
model_catalog_entry_response_instance = ModelCatalogEntryResponse.from_json(json)
# print the JSON string representation of the object
print(ModelCatalogEntryResponse.to_json())

# convert the object into a dict
model_catalog_entry_response_dict = model_catalog_entry_response_instance.to_dict()
# create an instance of ModelCatalogEntryResponse from a dict
model_catalog_entry_response_from_dict = ModelCatalogEntryResponse.from_dict(model_catalog_entry_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


