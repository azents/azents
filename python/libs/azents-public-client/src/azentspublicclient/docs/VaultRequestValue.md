# VaultRequestValue

A submit-only field whose value is never included in diagnostics.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**value** | **str** |  | 

## Example

```python
from azentspublicclient.models.vault_request_value import VaultRequestValue

# TODO update the JSON string below
json = "{}"
# create an instance of VaultRequestValue from a JSON string
vault_request_value_instance = VaultRequestValue.from_json(json)
# print the JSON string representation of the object
print(VaultRequestValue.to_json())

# convert the object into a dict
vault_request_value_dict = vault_request_value_instance.to_dict()
# create an instance of VaultRequestValue from a dict
vault_request_value_from_dict = VaultRequestValue.from_dict(vault_request_value_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


