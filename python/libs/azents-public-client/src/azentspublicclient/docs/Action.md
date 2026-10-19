# Action

Visible durable action payload

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'command']
**name** | **str** | Command name | 
**skill_path** | **str** | Exact SKILL.md path | 
**source_project_path** | **str** |  | 
**starting_ref** | **str** |  | 
**bridge_identity** | **str** |  | 
**originating_run_id** | **str** |  | 
**client_tool_call_id** | **str** |  | 
**session_agent_context_id** | **str** |  | 
**originating_agent_session_id** | **str** |  | 
**source_project_id** | **str** |  | 
**branch_name** | **str** |  | 
**worktree_project_id** | **str** |  | 
**worktree_allocation_id** | **str** |  | 
**worktree_path** | **str** |  | 
**force** | **bool** |  | 

## Example

```python
from azentspublicclient.models.action import Action

# TODO update the JSON string below
json = "{}"
# create an instance of Action from a JSON string
action_instance = Action.from_json(json)
# print the JSON string representation of the object
print(Action.to_json())

# convert the object into a dict
action_dict = action_instance.to_dict()
# create an instance of Action from a dict
action_from_dict = Action.from_dict(action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


