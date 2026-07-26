# PendingMailboxGoalContinuationPresentation

Safe pending Goal continuation presentation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**content** | **str** |  | 
**requested_inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | [optional] 

## Example

```python
from azentspublicclient.models.pending_mailbox_goal_continuation_presentation import PendingMailboxGoalContinuationPresentation

# TODO update the JSON string below
json = "{}"
# create an instance of PendingMailboxGoalContinuationPresentation from a JSON string
pending_mailbox_goal_continuation_presentation_instance = PendingMailboxGoalContinuationPresentation.from_json(json)
# print the JSON string representation of the object
print(PendingMailboxGoalContinuationPresentation.to_json())

# convert the object into a dict
pending_mailbox_goal_continuation_presentation_dict = pending_mailbox_goal_continuation_presentation_instance.to_dict()
# create an instance of PendingMailboxGoalContinuationPresentation from a dict
pending_mailbox_goal_continuation_presentation_from_dict = PendingMailboxGoalContinuationPresentation.from_dict(pending_mailbox_goal_continuation_presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


