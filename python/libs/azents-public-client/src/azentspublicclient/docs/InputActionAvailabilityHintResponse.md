# InputActionAvailabilityHintResponse

Non-authoritative composer action availability hint.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**state** | **str** | Hint state | 
**message** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.input_action_availability_hint_response import InputActionAvailabilityHintResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InputActionAvailabilityHintResponse from a JSON string
input_action_availability_hint_response_instance = InputActionAvailabilityHintResponse.from_json(json)
# print the JSON string representation of the object
print(InputActionAvailabilityHintResponse.to_json())

# convert the object into a dict
input_action_availability_hint_response_dict = input_action_availability_hint_response_instance.to_dict()
# create an instance of InputActionAvailabilityHintResponse from a dict
input_action_availability_hint_response_from_dict = InputActionAvailabilityHintResponse.from_dict(input_action_availability_hint_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


