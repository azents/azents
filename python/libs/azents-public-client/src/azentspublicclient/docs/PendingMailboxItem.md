# PendingMailboxItem

One stable pending mailbox presentation item.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**mailbox_item_id** | **str** |  | 
**item_key** | **str** |  | 
**kind** | **str** |  | 
**state** | **str** |  | [optional] [default to 'pending']
**created_at** | **datetime** |  | 
**presentation** | [**Presentation**](Presentation.md) |  | 

## Example

```python
from azentspublicclient.models.pending_mailbox_item import PendingMailboxItem

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxItem from a JSON string
pending_mailbox_item_instance = PendingMailboxItem.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxItem.to_json())

# convert the object into a dict
pending_mailbox_item_dict = pending_mailbox_item_instance.to_dict()
# create an instance of PendingMailboxItem from a dict
pending_mailbox_item_from_dict = PendingMailboxItem.from_dict(pending_mailbox_item_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


