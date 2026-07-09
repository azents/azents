# SystemModelCatalogRefreshListResponse

System model catalog refresh list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SystemModelCatalogRefreshResponse]**](SystemModelCatalogRefreshResponse.md) |  | 

## Example

```python
from azentsadminclient.models.system_model_catalog_refresh_list_response import SystemModelCatalogRefreshListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemModelCatalogRefreshListResponse from a JSON string
system_model_catalog_refresh_list_response_instance = SystemModelCatalogRefreshListResponse.from_json(json)
# print the JSON string representation of the object
print(SystemModelCatalogRefreshListResponse.to_json())

# convert the object into a dict
system_model_catalog_refresh_list_response_dict = system_model_catalog_refresh_list_response_instance.to_dict()
# create an instance of SystemModelCatalogRefreshListResponse from a dict
system_model_catalog_refresh_list_response_from_dict = SystemModelCatalogRefreshListResponse.from_dict(system_model_catalog_refresh_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


