# SkillAction

Skill invocation turn action.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'skill']
**skill_path** | **str** | Exact SKILL.md path |

## Example

```python
from azentspublicclient.models.skill_action import SkillAction

# TODO update the JSON string below
json = "{}"
# create an instance of SkillAction from a JSON string
skill_action_instance = SkillAction.from_json(json)
# print the JSON string representation of the object
print(SkillAction.to_json())

# convert the object into a dict
skill_action_dict = skill_action_instance.to_dict()
# create an instance of SkillAction from a dict
skill_action_from_dict = SkillAction.from_dict(skill_action_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


