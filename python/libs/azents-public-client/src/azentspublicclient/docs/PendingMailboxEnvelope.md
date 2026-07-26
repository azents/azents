# PendingMailboxEnvelope

Stable pending mailbox envelope projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mailbox_item_id** | **str** |  | 
**session_id** | **str** |  | 
**kind** | **str** |  | 
**scheduling_mode** | **str** |  | 
**created_at** | **datetime** |  | 
**items** | [**List[PendingMailboxItem]**](PendingMailboxItem.md) |  | 

## Example

```python
from azentspublicclient.models.pending_mailbox_envelope import PendingMailboxEnvelope

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxEnvelope from a JSON string
pending_mailbox_envelope_instance = PendingMailboxEnvelope.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxEnvelope.to_json())

# convert the object into a dict
pending_mailbox_envelope_dict = pending_mailbox_envelope_instance.to_dict()
# create an instance of PendingMailboxEnvelope from a dict
pending_mailbox_envelope_from_dict = PendingMailboxEnvelope.from_dict(pending_mailbox_envelope_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


