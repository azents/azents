# PendingMailboxUserMessagePresentation

Safe pending user-message presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**content** | **str** |  | 
**attachments** | **List[str]** |  | [optional] 
**file_parts** | [**List[FileOutputPart]**](FileOutputPart.md) |  | [optional] 
**requested_inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.pending_mailbox_user_message_presentation import PendingMailboxUserMessagePresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxUserMessagePresentation from a JSON string
pending_mailbox_user_message_presentation_instance = PendingMailboxUserMessagePresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxUserMessagePresentation.to_json())

# convert the object into a dict
pending_mailbox_user_message_presentation_dict = pending_mailbox_user_message_presentation_instance.to_dict()
# create an instance of PendingMailboxUserMessagePresentation from a dict
pending_mailbox_user_message_presentation_from_dict = PendingMailboxUserMessagePresentation.from_dict(pending_mailbox_user_message_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


