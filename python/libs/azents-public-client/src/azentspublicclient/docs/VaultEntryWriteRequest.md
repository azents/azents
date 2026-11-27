# VaultEntryWriteRequest

Explicit write of one named Vault value.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**value** | **str** |  | 

## Example

```python
from azentspublicclient.models.vault_entry_write_request import VaultEntryWriteRequest

# TODO update the JSON string below
json = "{}"
# create an instance of VaultEntryWriteRequest from a JSON string
vault_entry_write_request_instance = VaultEntryWriteRequest.from_json(json)
# print the JSON string representation of the object
print(VaultEntryWriteRequest.to_json())

# convert the object into a dict
vault_entry_write_request_dict = vault_entry_write_request_instance.to_dict()
# create an instance of VaultEntryWriteRequest from a dict
vault_entry_write_request_from_dict = VaultEntryWriteRequest.from_dict(vault_entry_write_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


