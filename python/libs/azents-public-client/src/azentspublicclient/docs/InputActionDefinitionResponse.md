# InputActionDefinitionResponse

Composer action definition response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Action definition ID | 
**keyword** | **str** | Slash search keyword | 
**label** | **str** | Action label | 
**description** | **str** | Action description | 
**action** | [**Action1**](Action1.md) |  | 
**category** | **str** | Action category | 
**message** | [**InputActionMessagePolicyResponse**](InputActionMessagePolicyResponse.md) | Message policy | 
**attachments** | [**InputActionAttachmentPolicyResponse**](InputActionAttachmentPolicyResponse.md) | Attachment policy | 
**availability_hint** | [**InputActionAvailabilityHintResponse**](InputActionAvailabilityHintResponse.md) |  | [optional] 
**source_label** | **str** |  | [optional] 
**relative_hint** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.input_action_definition_response import InputActionDefinitionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InputActionDefinitionResponse from a JSON string
input_action_definition_response_instance = InputActionDefinitionResponse.from_json(json)
# print the JSON string representation of the object
print(InputActionDefinitionResponse.to_json())

# convert the object into a dict
input_action_definition_response_dict = input_action_definition_response_instance.to_dict()
# create an instance of InputActionDefinitionResponse from a dict
input_action_definition_response_from_dict = InputActionDefinitionResponse.from_dict(input_action_definition_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


