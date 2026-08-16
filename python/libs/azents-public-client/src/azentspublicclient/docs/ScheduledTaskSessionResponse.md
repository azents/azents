# ScheduledTaskSessionResponse

Canonical Session navigation identity.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**handle** | **str** |  | 
**title** | **str** |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_session_response import ScheduledTaskSessionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskSessionResponse from a JSON string
scheduled_task_session_response_instance = ScheduledTaskSessionResponse.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskSessionResponse.to_json())

# convert the object into a dict
scheduled_task_session_response_dict = scheduled_task_session_response_instance.to_dict()
# create an instance of ScheduledTaskSessionResponse from a dict
scheduled_task_session_response_from_dict = ScheduledTaskSessionResponse.from_dict(scheduled_task_session_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


