# AgentToolkitConfigUpdateRequest

Agent-owned Toolkit Config partial update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**slug** | **str** | Unique within the owning Agent&#39;s effective Toolkit namespace. Use lowercase letters, numbers, and underscores only. | [optional] 
**name** | **str** | Display name | [optional] 
**description** | **str** |  | [optional] 
**config** | **Dict[str, object]** | Tool settings | [optional] 
**prompt** | **str** |  | [optional] 
**credentials** | **Dict[str, object]** |  | [optional] 
**enabled** | **bool** | Enabled flag | [optional] 
**always_expose_tools** | **bool** | Whether every tool bypasses Tool Search and remains visible | [optional] 

## Example

```python
from azentspublicclient.models.agent_toolkit_config_update_request import AgentToolkitConfigUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitConfigUpdateRequest from a JSON string
agent_toolkit_config_update_request_instance = AgentToolkitConfigUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitConfigUpdateRequest.to_json())

# convert the object into a dict
agent_toolkit_config_update_request_dict = agent_toolkit_config_update_request_instance.to_dict()
# create an instance of AgentToolkitConfigUpdateRequest from a dict
agent_toolkit_config_update_request_from_dict = AgentToolkitConfigUpdateRequest.from_dict(agent_toolkit_config_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


