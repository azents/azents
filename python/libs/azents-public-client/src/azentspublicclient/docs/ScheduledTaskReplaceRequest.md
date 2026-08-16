# ScheduledTaskReplaceRequest

Replace editable fields that govern future work.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**title** | **str** |  | 
**objective** | **str** |  | 
**at** | **str** |  | 
**cron** | **str** |  | 
**timezone** | **str** |  | 
**channel_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_replace_request import ScheduledTaskReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskReplaceRequest from a JSON string
scheduled_task_replace_request_instance = ScheduledTaskReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskReplaceRequest.to_json())

# convert the object into a dict
scheduled_task_replace_request_dict = scheduled_task_replace_request_instance.to_dict()
# create an instance of ScheduledTaskReplaceRequest from a dict
scheduled_task_replace_request_from_dict = ScheduledTaskReplaceRequest.from_dict(scheduled_task_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


