# ToolkitConfigListResponse

Toolkit Config list response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ToolkitConfigResponse]**](ToolkitConfigResponse.md) |  | 

## Example

```python
from azentspublicclient.models.toolkit_config_list_response import ToolkitConfigListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitConfigListResponse from a JSON string
toolkit_config_list_response_instance = ToolkitConfigListResponse.from_json(json)
# print the JSON string representation of the object
print(ToolkitConfigListResponse.to_json())

# convert the object into a dict
toolkit_config_list_response_dict = toolkit_config_list_response_instance.to_dict()
# create an instance of ToolkitConfigListResponse from a dict
toolkit_config_list_response_from_dict = ToolkitConfigListResponse.from_dict(toolkit_config_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


