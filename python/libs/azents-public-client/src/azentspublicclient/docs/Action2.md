# Action2


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
from azentspublicclient.models.action2 import Action2

# TODO update the JSON string below
json = "{}"
# create an instance of Action2 from a JSON string
action2_instance = Action2.from_json(json)
# print the JSON string representation of the object
print(Action2.to_json())

# convert the object into a dict
action2_dict = action2_instance.to_dict()
# create an instance of Action2 from a dict
action2_from_dict = Action2.from_dict(action2_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


