# SystemSettingInventoryItemResponse

Generic System Settings inventory item.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**section** | **str** |  |
**display_name** | **str** |  |
**effective_status** | [**PlatformGitHubAppEffectiveStatus**](PlatformGitHubAppEffectiveStatus.md) |  |
**admin_version** | **int** |  |
**environment_managed_field_count** | **int** |  |
**candidate_status** | [**SystemSettingValidationStatus**](SystemSettingValidationStatus.md) |  |

## Example

```python
from azentsadminclient.models.system_setting_inventory_item_response import SystemSettingInventoryItemResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SystemSettingInventoryItemResponse from a JSON string
system_setting_inventory_item_response_instance = SystemSettingInventoryItemResponse.from_json(json)
# print the JSON string representation of the object
print(SystemSettingInventoryItemResponse.to_json())

# convert the object into a dict
system_setting_inventory_item_response_dict = system_setting_inventory_item_response_instance.to_dict()
# create an instance of SystemSettingInventoryItemResponse from a dict
system_setting_inventory_item_response_from_dict = SystemSettingInventoryItemResponse.from_dict(system_setting_inventory_item_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
