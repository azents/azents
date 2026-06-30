# CommandAction

Idle-only prioritized command action.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'command']
**name** | **str** | Command name | 

## Example

```python
from azentspublicclient.models.command_action import CommandAction

# TODO update the JSON string below
json = "{}"
# create an instance of CommandAction from a JSON string
command_action_instance = CommandAction.from_json(json)
# print the JSON string representation of the object
print(CommandAction.to_json())

# convert the object into a dict
command_action_dict = command_action_instance.to_dict()
# create an instance of CommandAction from a dict
command_action_from_dict = CommandAction.from_dict(command_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


