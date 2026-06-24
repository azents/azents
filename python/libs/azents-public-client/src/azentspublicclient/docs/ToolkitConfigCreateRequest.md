# ToolkitConfigCreateRequest

Toolkit Config creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_type** | **str** | Tool slug |
**slug** | **str** |  | [optional]
**name** | **str** | Display name |
**description** | **str** |  | [optional]
**config** | **Dict[str, object]** | Tool configuration |
**prompt** | **str** |  | [optional]
**credentials** | **Dict[str, object]** |  | [optional]
**enabled** | **bool** | Enabled state | [optional] [default to True]

## Example

```python
from azentspublicclient.models.toolkit_config_create_request import ToolkitConfigCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ToolkitConfigCreateRequest from a JSON string
toolkit_config_create_request_instance = ToolkitConfigCreateRequest.from_json(json)
# print the JSON string representation of the object
print(ToolkitConfigCreateRequest.to_json())

# convert the object into a dict
toolkit_config_create_request_dict = toolkit_config_create_request_instance.to_dict()
# create an instance of ToolkitConfigCreateRequest from a dict
toolkit_config_create_request_from_dict = ToolkitConfigCreateRequest.from_dict(toolkit_config_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
