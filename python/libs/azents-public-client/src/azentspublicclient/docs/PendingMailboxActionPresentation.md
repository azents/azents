# PendingMailboxActionPresentation

Safe pending Turn Action presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**action** | [**Action2**](Action2.md) |  | 
**message** | **str** |  | 
**requested_inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.pending_mailbox_action_presentation import PendingMailboxActionPresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxActionPresentation from a JSON string
pending_mailbox_action_presentation_instance = PendingMailboxActionPresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxActionPresentation.to_json())

# convert the object into a dict
pending_mailbox_action_presentation_dict = pending_mailbox_action_presentation_instance.to_dict()
# create an instance of PendingMailboxActionPresentation from a dict
pending_mailbox_action_presentation_from_dict = PendingMailboxActionPresentation.from_dict(pending_mailbox_action_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


