# ModelCatalogEntryListResponse

Stored model catalog entry list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**catalog_id** | **str** |  |
**current_snapshot_id** | **str** |  |
**current_snapshot_created_at** | **datetime** |  |
**latest_attempt** | [**ModelCatalogSyncAttemptResponse**](ModelCatalogSyncAttemptResponse.md) |  |
**entries** | [**List[ModelCatalogEntryResponse]**](ModelCatalogEntryResponse.md) |  |
**total** | **int** |  |
**limit** | **int** |  |
**offset** | **int** |  |

## Example

```python
from azentspublicclient.models.model_catalog_entry_list_response import ModelCatalogEntryListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ModelCatalogEntryListResponse from a JSON string
model_catalog_entry_list_response_instance = ModelCatalogEntryListResponse.from_json(json)
# print the JSON string representation of the object
print(ModelCatalogEntryListResponse.to_json())

# convert the object into a dict
model_catalog_entry_list_response_dict = model_catalog_entry_list_response_instance.to_dict()
# create an instance of ModelCatalogEntryListResponse from a dict
model_catalog_entry_list_response_from_dict = ModelCatalogEntryListResponse.from_dict(model_catalog_entry_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


