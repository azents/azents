# SubagentTreeResponse

Subagent Tree response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**root_session_agent_id** | **str** | Root SessionAgent ID | 
**root_agent_session_id** | **str** | Root AgentSession ID | 
**current_session_agent_id** | **str** | Current SessionAgent ID | 
**nodes** | [**List[SubagentTreeNodeResponse]**](SubagentTreeNodeResponse.md) | Root tree nodes | 

## Example

```python
from azentspublicclient.models.subagent_tree_response import SubagentTreeResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SubagentTreeResponse from a JSON string
subagent_tree_response_instance = SubagentTreeResponse.from_json(json)
# print the JSON string representation of the object
print(SubagentTreeResponse.to_json())

# convert the object into a dict
subagent_tree_response_dict = subagent_tree_response_instance.to_dict()
# create an instance of SubagentTreeResponse from a dict
subagent_tree_response_from_dict = SubagentTreeResponse.from_dict(subagent_tree_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


