# ScheduledTaskListResponse

Ordered authorized Scheduled Task list.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ScheduledTaskResponse]**](ScheduledTaskResponse.md) |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_list_response import ScheduledTaskListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskListResponse from a JSON string
scheduled_task_list_response_instance = ScheduledTaskListResponse.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskListResponse.to_json())

# convert the object into a dict
scheduled_task_list_response_dict = scheduled_task_list_response_instance.to_dict()
# create an instance of ScheduledTaskListResponse from a dict
scheduled_task_list_response_from_dict = ScheduledTaskListResponse.from_dict(scheduled_task_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


