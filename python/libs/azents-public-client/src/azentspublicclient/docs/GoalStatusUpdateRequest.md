# GoalStatusUpdateRequest

User-controlled Goal status update request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | **str** | User-controlled goal status. Active resumes paused or blocked goals; paused pauses active goals. | 
**resume_hint** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.goal_status_update_request import GoalStatusUpdateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of GoalStatusUpdateRequest from a JSON string
goal_status_update_request_instance = GoalStatusUpdateRequest.from_json(json)
# print the JSON string representation of the object
print(GoalStatusUpdateRequest.to_json())

# convert the object into a dict
goal_status_update_request_dict = goal_status_update_request_instance.to_dict()
# create an instance of GoalStatusUpdateRequest from a dict
goal_status_update_request_from_dict = GoalStatusUpdateRequest.from_dict(goal_status_update_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


