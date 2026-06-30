# ToolkitConfigUpdateRequest

Toolkit Config update request, for partial updates.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**slug** | **str** | Workspace-unique slug. Use lowercase letters, numbers, and underscores only. | [optional] 
**name** | **str** | Display name | [optional] 
**description** | **str** |  | [optional] 
**config** | **Dict[str, object]** | Tool settings | [optional] 
**prompt** | **str** |  | [optional] 
**credentials** | **Dict[str, object]** |  | [optional] 
**enabled** | **bool** | Enabled flag | [optional] 

## Example

```python
from azentspublicclient.models.toolkit_config_update_request import ToolkitConfigUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitConfigUpdateRequest from a JSON string
toolkit_config_update_request_instance = ToolkitConfigUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(ToolkitConfigUpdateRequest.to_json())

# convert the object into a dict
toolkit_config_update_request_dict = toolkit_config_update_request_instance.to_dict()
# create an instance of ToolkitConfigUpdateRequest from a dict
toolkit_config_update_request_from_dict = ToolkitConfigUpdateRequest.from_dict(toolkit_config_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


