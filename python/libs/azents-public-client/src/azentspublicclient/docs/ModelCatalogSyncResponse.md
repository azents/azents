# ModelCatalogSyncResponse

Model catalog sync response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**LLMProvider**](LLMProvider.md) |  |
**catalog_id** | **str** |  |
**snapshot_id** | **str** |  |
**visible_count** | **int** |  |
**hidden_count** | **int** |  |
**status** | **str** |  |
**failure_code** | **str** |  |
**failure_message** | **str** |  |
**action_hint** | **str** |  |

## Example

```python
from azentspublicclient.models.model_catalog_sync_response import ModelCatalogSyncResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCatalogSyncResponse from a JSON string
model_catalog_sync_response_instance = ModelCatalogSyncResponse.from_json(json)
# print the JSON string representation of the object
print(ModelCatalogSyncResponse.to_json())

# convert the object into a dict
model_catalog_sync_response_dict = model_catalog_sync_response_instance.to_dict()
# create an instance of ModelCatalogSyncResponse from a dict
model_catalog_sync_response_from_dict = ModelCatalogSyncResponse.from_dict(model_catalog_sync_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
