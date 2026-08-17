# ScheduledTaskResponse

Sanitized Scheduled Task management projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**title** | **str** |  | 
**objective** | **str** |  | 
**schedule_type** | [**ScheduledTaskScheduleType**](ScheduledTaskScheduleType.md) |  | 
**scheduled_at** | **datetime** |  | 
**cron_expression** | **str** |  | 
**timezone** | **str** |  | 
**next_eligible_at** | **datetime** |  | 
**execution_state** | **str** |  | 
**session** | [**ScheduledTaskSessionResponse**](ScheduledTaskSessionResponse.md) |  | 
**target** | [**ScheduledTaskTargetResponse**](ScheduledTaskTargetResponse.md) |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_response import ScheduledTaskResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskResponse from a JSON string
scheduled_task_response_instance = ScheduledTaskResponse.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskResponse.to_json())

# convert the object into a dict
scheduled_task_response_dict = scheduled_task_response_instance.to_dict()
# create an instance of ScheduledTaskResponse from a dict
scheduled_task_response_from_dict = ScheduledTaskResponse.from_dict(scheduled_task_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


