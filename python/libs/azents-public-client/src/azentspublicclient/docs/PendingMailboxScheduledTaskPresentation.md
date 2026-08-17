# PendingMailboxScheduledTaskPresentation

Safe pending Scheduled Task presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**content** | **str** |  | 

## Example

```python
from azentspublicclient.models.pending_mailbox_scheduled_task_presentation import PendingMailboxScheduledTaskPresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxScheduledTaskPresentation from a JSON string
pending_mailbox_scheduled_task_presentation_instance = PendingMailboxScheduledTaskPresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxScheduledTaskPresentation.to_json())

# convert the object into a dict
pending_mailbox_scheduled_task_presentation_dict = pending_mailbox_scheduled_task_presentation_instance.to_dict()
# create an instance of PendingMailboxScheduledTaskPresentation from a dict
pending_mailbox_scheduled_task_presentation_from_dict = PendingMailboxScheduledTaskPresentation.from_dict(pending_mailbox_scheduled_task_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


