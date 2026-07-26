# PendingMailboxAgentMessagePresentation

Safe pending Agent-to-Agent message presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**message_kind** | **str** |  | 
**content** | **str** |  | 

## Example

```python
from azentspublicclient.models.pending_mailbox_agent_message_presentation import PendingMailboxAgentMessagePresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxAgentMessagePresentation from a JSON string
pending_mailbox_agent_message_presentation_instance = PendingMailboxAgentMessagePresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxAgentMessagePresentation.to_json())

# convert the object into a dict
pending_mailbox_agent_message_presentation_dict = pending_mailbox_agent_message_presentation_instance.to_dict()
# create an instance of PendingMailboxAgentMessagePresentation from a dict
pending_mailbox_agent_message_presentation_from_dict = PendingMailboxAgentMessagePresentation.from_dict(pending_mailbox_agent_message_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


