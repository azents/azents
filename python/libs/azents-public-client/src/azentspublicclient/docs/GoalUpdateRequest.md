# GoalUpdateRequest

Session goal update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**objective** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.goal_update_request import GoalUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GoalUpdateRequest from a JSON string
goal_update_request_instance = GoalUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(GoalUpdateRequest.to_json())

# convert the object into a dict
goal_update_request_dict = goal_update_request_instance.to_dict()
# create an instance of GoalUpdateRequest from a dict
goal_update_request_from_dict = GoalUpdateRequest.from_dict(goal_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


