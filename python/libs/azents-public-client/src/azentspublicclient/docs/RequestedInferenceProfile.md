# RequestedInferenceProfile

Agent-owned target label and optional explicit reasoning effort.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**model_target_label** | **str** | Agent-owned selectable model target label |
**reasoning_effort** | [**ModelReasoningEffort**](ModelReasoningEffort.md) |  |

## Example

```python
from azentspublicclient.models.requested_inference_profile import RequestedInferenceProfile

# TODO update the JSON string below
json = "{}"
# create an instance of RequestedInferenceProfile from a JSON string
requested_inference_profile_instance = RequestedInferenceProfile.from_json(json)
# print the JSON string representation of the object
print(RequestedInferenceProfile.to_json())

# convert the object into a dict
requested_inference_profile_dict = requested_inference_profile_instance.to_dict()
# create an instance of RequestedInferenceProfile from a dict
requested_inference_profile_from_dict = RequestedInferenceProfile.from_dict(requested_inference_profile_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
