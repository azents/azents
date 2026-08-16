# ScheduledTaskCreateRequest

Create one Task for an existing authorized Session.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** |  | 
**title** | **str** |  | 
**objective** | **str** |  | 
**at** | **str** |  | 
**cron** | **str** |  | 
**timezone** | **str** |  | 
**channel_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_create_request import ScheduledTaskCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskCreateRequest from a JSON string
scheduled_task_create_request_instance = ScheduledTaskCreateRequest.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskCreateRequest.to_json())

# convert the object into a dict
scheduled_task_create_request_dict = scheduled_task_create_request_instance.to_dict()
# create an instance of ScheduledTaskCreateRequest from a dict
scheduled_task_create_request_from_dict = ScheduledTaskCreateRequest.from_dict(scheduled_task_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


