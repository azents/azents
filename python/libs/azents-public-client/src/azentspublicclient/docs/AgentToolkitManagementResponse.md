# AgentToolkitManagementResponse

Authorized Agent Toolkit management projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentToolkitManagementItemResponse]**](AgentToolkitManagementItemResponse.md) |  | 
**available_shared** | [**List[ToolkitConfigResponse]**](ToolkitConfigResponse.md) |  | 

## Example

```python
from azentspublicclient.models.agent_toolkit_management_response import AgentToolkitManagementResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitManagementResponse from a JSON string
agent_toolkit_management_response_instance = AgentToolkitManagementResponse.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitManagementResponse.to_json())

# convert the object into a dict
agent_toolkit_management_response_dict = agent_toolkit_management_response_instance.to_dict()
# create an instance of AgentToolkitManagementResponse from a dict
agent_toolkit_management_response_from_dict = AgentToolkitManagementResponse.from_dict(agent_toolkit_management_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


