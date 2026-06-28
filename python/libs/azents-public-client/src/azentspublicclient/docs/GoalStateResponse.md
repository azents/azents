# GoalStateResponse

Chat live goal state response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**objective** | **str** |  | [optional]
**status** | **str** |  | [optional]
**created_at** | **str** |  | [optional]
**updated_at** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.goal_state_response import GoalStateResponse

# TODO update the JSON string below
json = "{}"
# create an instance of GoalStateResponse from a JSON string
goal_state_response_instance = GoalStateResponse.from_json(json)
# print the JSON string representation of the object
print(GoalStateResponse.to_json())

# convert the object into a dict
goal_state_response_dict = goal_state_response_instance.to_dict()
# create an instance of GoalStateResponse from a dict
goal_state_response_from_dict = GoalStateResponse.from_dict(goal_state_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


