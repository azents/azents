# AgentVaultEntryMetadata

Vault entry metadata without a value.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**contributor_label** | **str** |  | 

## Example

```python
from azentspublicclient.models.agent_vault_entry_metadata import AgentVaultEntryMetadata

# TODO update the JSON string below
json = "{}"
# create an instance of AgentVaultEntryMetadata from a JSON string
agent_vault_entry_metadata_instance = AgentVaultEntryMetadata.from_json(json)
# print the JSON string representation of the object
print(AgentVaultEntryMetadata.to_json())

# convert the object into a dict
agent_vault_entry_metadata_dict = agent_vault_entry_metadata_instance.to_dict()
# create an instance of AgentVaultEntryMetadata from a dict
agent_vault_entry_metadata_from_dict = AgentVaultEntryMetadata.from_dict(agent_vault_entry_metadata_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


