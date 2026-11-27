# VaultRequestSubmission

One value per requested exact name, with duplicates explicitly detectable.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**values** | [**List[VaultRequestValue]**](VaultRequestValue.md) |  | 

## Example

```python
from azentspublicclient.models.vault_request_submission import VaultRequestSubmission

# TODO update the JSON string below
json = "{}"
# create an instance of VaultRequestSubmission from a JSON string
vault_request_submission_instance = VaultRequestSubmission.from_json(json)
# print the JSON string representation of the object
print(VaultRequestSubmission.to_json())

# convert the object into a dict
vault_request_submission_dict = vault_request_submission_instance.to_dict()
# create an instance of VaultRequestSubmission from a dict
vault_request_submission_from_dict = VaultRequestSubmission.from_dict(vault_request_submission_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


