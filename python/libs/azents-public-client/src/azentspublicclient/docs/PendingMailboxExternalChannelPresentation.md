# PendingMailboxExternalChannelPresentation

Safe pending External Channel message presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**provider** | **str** |  | 
**resource_label** | **str** |  | 
**resource_type** | **str** |  | 
**external_message_id** | **str** |  | 
**sender_display_name** | **str** |  | 
**author_type** | **str** |  | 
**prompt_role** | **str** |  | 
**body** | **str** |  | 
**reference_mappings** | **Dict[str, Dict[str, str]]** |  | 
**original_url** | **str** |  | 

## Example

```python
from azentspublicclient.models.pending_mailbox_external_channel_presentation import PendingMailboxExternalChannelPresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxExternalChannelPresentation from a JSON string
pending_mailbox_external_channel_presentation_instance = PendingMailboxExternalChannelPresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxExternalChannelPresentation.to_json())

# convert the object into a dict
pending_mailbox_external_channel_presentation_dict = pending_mailbox_external_channel_presentation_instance.to_dict()
# create an instance of PendingMailboxExternalChannelPresentation from a dict
pending_mailbox_external_channel_presentation_from_dict = PendingMailboxExternalChannelPresentation.from_dict(pending_mailbox_external_channel_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


