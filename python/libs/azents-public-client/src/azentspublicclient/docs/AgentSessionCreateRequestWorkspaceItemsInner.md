# AgentSessionCreateRequestWorkspaceItemsInner


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace item type | 
**path** | **str** | Existing Project path | 
**source_project_path** | **str** | Source Project path | 
**starting_ref** | **str** | Starting local Git branch ref | 

## Example

```python
from azentspublicclient.models.agent_session_create_request_workspace_items_inner import AgentSessionCreateRequestWorkspaceItemsInner

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionCreateRequestWorkspaceItemsInner from a JSON string
agent_session_create_request_workspace_items_inner_instance = AgentSessionCreateRequestWorkspaceItemsInner.from_json(json)
# print the JSON string representation of the object
print(AgentSessionCreateRequestWorkspaceItemsInner.to_json())

# convert the object into a dict
agent_session_create_request_workspace_items_inner_dict = agent_session_create_request_workspace_items_inner_instance.to_dict()
# create an instance of AgentSessionCreateRequestWorkspaceItemsInner from a dict
agent_session_create_request_workspace_items_inner_from_dict = AgentSessionCreateRequestWorkspaceItemsInner.from_dict(agent_session_create_request_workspace_items_inner_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


