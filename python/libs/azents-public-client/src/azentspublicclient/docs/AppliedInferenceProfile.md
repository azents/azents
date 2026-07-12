# AppliedInferenceProfile

Resolved user-visible inference settings applied by one message.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**model_target_label** | **str** | Agent-owned model target label applied by the message |
**model_display_name** | **str** |  | [optional]
**reasoning_effort** | [**ModelReasoningEffort**](ModelReasoningEffort.md) |  |

## Example

```python
from azentspublicclient.models.applied_inference_profile import AppliedInferenceProfile

# TODO update the JSON string below
json = "{}"
# create an instance of AppliedInferenceProfile from a JSON string
applied_inference_profile_instance = AppliedInferenceProfile.from_json(json)
# print the JSON string representation of the object
print(AppliedInferenceProfile.to_json())

# convert the object into a dict
applied_inference_profile_dict = applied_inference_profile_instance.to_dict()
# create an instance of AppliedInferenceProfile from a dict
applied_inference_profile_from_dict = AppliedInferenceProfile.from_dict(applied_inference_profile_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


