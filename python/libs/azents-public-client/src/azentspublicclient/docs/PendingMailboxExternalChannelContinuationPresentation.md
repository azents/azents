# PendingMailboxExternalChannelContinuationPresentation

Safe pending External Channel continuation presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**content** | **str** |  | 
**requested_inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.pending_mailbox_external_channel_continuation_presentation import PendingMailboxExternalChannelContinuationPresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxExternalChannelContinuationPresentation from a JSON string
pending_mailbox_external_channel_continuation_presentation_instance = PendingMailboxExternalChannelContinuationPresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxExternalChannelContinuationPresentation.to_json())

# convert the object into a dict
pending_mailbox_external_channel_continuation_presentation_dict = pending_mailbox_external_channel_continuation_presentation_instance.to_dict()
# create an instance of PendingMailboxExternalChannelContinuationPresentation from a dict
pending_mailbox_external_channel_continuation_presentation_from_dict = PendingMailboxExternalChannelContinuationPresentation.from_dict(pending_mailbox_external_channel_continuation_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


