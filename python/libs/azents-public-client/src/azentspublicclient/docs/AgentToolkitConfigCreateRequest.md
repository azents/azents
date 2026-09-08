# AgentToolkitConfigCreateRequest

Agent-owned Toolkit Config creation request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_type** | **str** | Tool slug | 
**slug** | **str** | Unique within the owning Agent&#39;s effective Toolkit namespace. Use lowercase letters, numbers, and underscores only. | [optional] 
**name** | **str** | Display name | 
**description** | **str** |  | [optional] 
**config** | **Dict[str, object]** | Tool configuration | 
**prompt** | **str** |  | [optional] 
**credentials** | **Dict[str, object]** |  | [optional] 
**enabled** | **bool** | Enabled state | [optional] [default to True]
**always_expose_tools** | **bool** | Expose every toolkit tool directly instead of through Tool Search | [optional] [default to False]

## Example

```python
from azentspublicclient.models.agent_toolkit_config_create_request import AgentToolkitConfigCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitConfigCreateRequest from a JSON string
agent_toolkit_config_create_request_instance = AgentToolkitConfigCreateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitConfigCreateRequest.to_json())

# convert the object into a dict
agent_toolkit_config_create_request_dict = agent_toolkit_config_create_request_instance.to_dict()
# create an instance of AgentToolkitConfigCreateRequest from a dict
agent_toolkit_config_create_request_from_dict = AgentToolkitConfigCreateRequest.from_dict(agent_toolkit_config_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


