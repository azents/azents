# GoalAction

Session goal creation turn action.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'goal']

## Example

```python
from azentspublicclient.models.goal_action import GoalAction

# TODO update the JSON string below
json = "{}"
# create an instance of GoalAction from a JSON string
goal_action_instance = GoalAction.from_json(json)
# print the JSON string representation of the object
print(GoalAction.to_json())

# convert the object into a dict
goal_action_dict = goal_action_instance.to_dict()
# create an instance of GoalAction from a dict
goal_action_from_dict = GoalAction.from_dict(goal_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


