# ScheduledTaskCurrentCycleResponse

Sanitized current occurrence projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**phase** | **str** |  | 
**scheduled_for** | **datetime** |  | 
**started_at** | **datetime** |  | 
**progress_title** | **str** |  | 
**ordered_tasks** | **List[str]** |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_current_cycle_response import ScheduledTaskCurrentCycleResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskCurrentCycleResponse from a JSON string
scheduled_task_current_cycle_response_instance = ScheduledTaskCurrentCycleResponse.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskCurrentCycleResponse.to_json())

# convert the object into a dict
scheduled_task_current_cycle_response_dict = scheduled_task_current_cycle_response_instance.to_dict()
# create an instance of ScheduledTaskCurrentCycleResponse from a dict
scheduled_task_current_cycle_response_from_dict = ScheduledTaskCurrentCycleResponse.from_dict(scheduled_task_current_cycle_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


