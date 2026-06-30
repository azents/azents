# InputActionMessagePolicyResponse

Composer action message policy.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**policy** | **str** | Message input policy | 
**placeholder** | **str** |  | [optional] 
**max_length** | **int** |  | [optional] 

## Example

```python
from azentspublicclient.models.input_action_message_policy_response import InputActionMessagePolicyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InputActionMessagePolicyResponse from a JSON string
input_action_message_policy_response_instance = InputActionMessagePolicyResponse.from_json(json)
# print the JSON string representation of the object
print(InputActionMessagePolicyResponse.to_json())

# convert the object into a dict
input_action_message_policy_response_dict = input_action_message_policy_response_instance.to_dict()
# create an instance of InputActionMessagePolicyResponse from a dict
input_action_message_policy_response_from_dict = InputActionMessagePolicyResponse.from_dict(input_action_message_policy_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


