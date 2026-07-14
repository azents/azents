# SystemModelCatalogResponse

System model catalog response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**SystemCatalogProvider**](SystemCatalogProvider.md) |  |
**catalog_id** | **str** |  |
**snapshot_id** | **str** |  |
**visible_count** | **int** |  |
**hidden_count** | **int** |  |
**latest_attempt** | [**SystemModelCatalogSyncAttemptResponse**](SystemModelCatalogSyncAttemptResponse.md) |  |

## Example

```python
from azentsadminclient.models.system_model_catalog_response import SystemModelCatalogResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemModelCatalogResponse from a JSON string
system_model_catalog_response_instance = SystemModelCatalogResponse.from_json(json)
# print the JSON string representation of the object
print(SystemModelCatalogResponse.to_json())

# convert the object into a dict
system_model_catalog_response_dict = system_model_catalog_response_instance.to_dict()
# create an instance of SystemModelCatalogResponse from a dict
system_model_catalog_response_from_dict = SystemModelCatalogResponse.from_dict(system_model_catalog_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
