# ScheduledTaskTargetResponse

Opaque External Channel target presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**channel_id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**location** | [**ExternalChannelConversationLocation**](ExternalChannelConversationLocation.md) |  | 
**label** | **str** |  | 

## Example

```python
from azentspublicclient.models.scheduled_task_target_response import ScheduledTaskTargetResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ScheduledTaskTargetResponse from a JSON string
scheduled_task_target_response_instance = ScheduledTaskTargetResponse.from_json(json)
# print the JSON string representation of the object
print(ScheduledTaskTargetResponse.to_json())

# convert the object into a dict
scheduled_task_target_response_dict = scheduled_task_target_response_instance.to_dict()
# create an instance of ScheduledTaskTargetResponse from a dict
scheduled_task_target_response_from_dict = ScheduledTaskTargetResponse.from_dict(scheduled_task_target_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


