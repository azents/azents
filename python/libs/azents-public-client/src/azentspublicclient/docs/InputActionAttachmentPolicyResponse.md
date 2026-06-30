# InputActionAttachmentPolicyResponse

Composer action attachment policy.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**policy** | **str** | Attachment policy | 

## Example

```python
from azentspublicclient.models.input_action_attachment_policy_response import InputActionAttachmentPolicyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of InputActionAttachmentPolicyResponse from a JSON string
input_action_attachment_policy_response_instance = InputActionAttachmentPolicyResponse.from_json(json)
# print the JSON string representation of the object
print(InputActionAttachmentPolicyResponse.to_json())

# convert the object into a dict
input_action_attachment_policy_response_dict = input_action_attachment_policy_response_instance.to_dict()
# create an instance of InputActionAttachmentPolicyResponse from a dict
input_action_attachment_policy_response_from_dict = InputActionAttachmentPolicyResponse.from_dict(input_action_attachment_policy_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


