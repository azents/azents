# SystemSettingInventoryResponse

System Settings inventory response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[SystemSettingInventoryItemResponse]**](SystemSettingInventoryItemResponse.md) |  | 

## Example

```python
from azentsadminclient.models.system_setting_inventory_response import SystemSettingInventoryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingInventoryResponse from a JSON string
system_setting_inventory_response_instance = SystemSettingInventoryResponse.from_json(json)
# print the JSON string representation of the object
print(SystemSettingInventoryResponse.to_json())

# convert the object into a dict
system_setting_inventory_response_dict = system_setting_inventory_response_instance.to_dict()
# create an instance of SystemSettingInventoryResponse from a dict
system_setting_inventory_response_from_dict = SystemSettingInventoryResponse.from_dict(system_setting_inventory_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


