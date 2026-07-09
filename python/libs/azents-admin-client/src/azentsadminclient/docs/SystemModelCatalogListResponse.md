# SystemModelCatalogListResponse

System model catalog list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SystemModelCatalogResponse]**](SystemModelCatalogResponse.md) |  | 

## Example

```python
from azentsadminclient.models.system_model_catalog_list_response import SystemModelCatalogListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemModelCatalogListResponse from a JSON string
system_model_catalog_list_response_instance = SystemModelCatalogListResponse.from_json(json)
# print the JSON string representation of the object
print(SystemModelCatalogListResponse.to_json())

# convert the object into a dict
system_model_catalog_list_response_dict = system_model_catalog_list_response_instance.to_dict()
# create an instance of SystemModelCatalogListResponse from a dict
system_model_catalog_list_response_from_dict = SystemModelCatalogListResponse.from_dict(system_model_catalog_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


