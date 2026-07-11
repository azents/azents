# SubagentTreeNodeResponse

Subagent Tree node response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_agent_id** | **str** | SessionAgent ID | 
**agent_session_id** | **str** | Linked AgentSession ID | 
**parent_session_agent_id** | **str** |  | [optional] 
**name** | **str** | SessionAgent local name | 
**path** | **str** | Canonical absolute SessionAgent path | 
**agent_type** | **str** | Spawned agent type snapshot | 
**status** | **str** | Projected execution status | 
**last_task_message** | **str** |  | [optional] 
**last_message_at** | **datetime** |  | [optional] 
**unread_result** | **bool** | Whether latest terminal result is unread | 
**latest_run_id** | **str** |  | [optional] 
**latest_run_index** | **int** |  | [optional] 
**latest_run_status** | [**AgentRunStatus**](AgentRunStatus.md) |  | [optional] 
**terminal_result_event_id** | **str** |  | [optional] 
**terminal_result_message** | **str** |  | [optional] 
**children** | [**List[SubagentTreeNodeResponse]**](SubagentTreeNodeResponse.md) | Child SessionAgents | [optional] 

## Example

```python
from azentspublicclient.models.subagent_tree_node_response import SubagentTreeNodeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SubagentTreeNodeResponse from a JSON string
subagent_tree_node_response_instance = SubagentTreeNodeResponse.from_json(json)
# print the JSON string representation of the object
print(SubagentTreeNodeResponse.to_json())

# convert the object into a dict
subagent_tree_node_response_dict = subagent_tree_node_response_instance.to_dict()
# create an instance of SubagentTreeNodeResponse from a dict
subagent_tree_node_response_from_dict = SubagentTreeNodeResponse.from_dict(subagent_tree_node_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


