# Action1

Action payload

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'command']
**name** | **str** | Command name | 
**skill_path** | **str** | Exact SKILL.md path | 
**source_project_path** | **str** | Existing source Project path under the Agent Workspace | 
**starting_ref** | **str** | Starting Git ref for the new worktree branch | 

## Example

```python
from azentspublicclient.models.action1 import Action1

# TODO update the JSON string below
json = "{}"
# create an instance of Action1 from a JSON string
action1_instance = Action1.from_json(json)
# print the JSON string representation of the object
print(Action1.to_json())

# convert the object into a dict
action1_dict = action1_instance.to_dict()
# create an instance of Action1 from a dict
action1_from_dict = Action1.from_dict(action1_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


