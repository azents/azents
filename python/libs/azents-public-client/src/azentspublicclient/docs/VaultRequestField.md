# VaultRequestField

One exact Vault entry name and the label shown to a submitter.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**label** | **str** |  | 

## Example

```python
from azentspublicclient.models.vault_request_field import VaultRequestField

# TODO update the JSON string below
json = "{}"
# create an instance of VaultRequestField from a JSON string
vault_request_field_instance = VaultRequestField.from_json(json)
# print the JSON string representation of the object
print(VaultRequestField.to_json())

# convert the object into a dict
vault_request_field_dict = vault_request_field_instance.to_dict()
# create an instance of VaultRequestField from a dict
vault_request_field_from_dict = VaultRequestField.from_dict(vault_request_field_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


