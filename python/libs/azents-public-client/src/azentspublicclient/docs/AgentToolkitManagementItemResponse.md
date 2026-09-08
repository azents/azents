# AgentToolkitManagementItemResponse

One Toolkit in the authorized Agent management projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**ownership_scope** | **str** |  | 
**toolkit** | [**ToolkitConfigResponse**](ToolkitConfigResponse.md) |  | 
**agent_toolkit_id** | **str** |  | 
**readiness** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_toolkit_management_item_response import AgentToolkitManagementItemResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitManagementItemResponse from a JSON string
agent_toolkit_management_item_response_instance = AgentToolkitManagementItemResponse.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitManagementItemResponse.to_json())

# convert the object into a dict
agent_toolkit_management_item_response_dict = agent_toolkit_management_item_response_instance.to_dict()
# create an instance of AgentToolkitManagementItemResponse from a dict
agent_toolkit_management_item_response_from_dict = AgentToolkitManagementItemResponse.from_dict(agent_toolkit_management_item_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


