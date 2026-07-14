# SystemModelCatalogRefreshResponse

System model catalog refresh response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**SystemCatalogProvider**](SystemCatalogProvider.md) |  |
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
from azentsadminclient.models.system_model_catalog_refresh_response import SystemModelCatalogRefreshResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemModelCatalogRefreshResponse from a JSON string
system_model_catalog_refresh_response_instance = SystemModelCatalogRefreshResponse.from_json(json)
# print the JSON string representation of the object
print(SystemModelCatalogRefreshResponse.to_json())

# convert the object into a dict
system_model_catalog_refresh_response_dict = system_model_catalog_refresh_response_instance.to_dict()
# create an instance of SystemModelCatalogRefreshResponse from a dict
system_model_catalog_refresh_response_from_dict = SystemModelCatalogRefreshResponse.from_dict(system_model_catalog_refresh_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
