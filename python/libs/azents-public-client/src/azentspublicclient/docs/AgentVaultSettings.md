# AgentVaultSettings

Authorized Vault settings projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**entries** | [**List[AgentVaultEntryMetadata]**](AgentVaultEntryMetadata.md) |  | 

## Example

```python
from azentspublicclient.models.agent_vault_settings import AgentVaultSettings

# TODO update the JSON string below
json = "{}"
# create an instance of AgentVaultSettings from a JSON string
agent_vault_settings_instance = AgentVaultSettings.from_json(json)
# print the JSON string representation of the object
print(AgentVaultSettings.to_json())

# convert the object into a dict
agent_vault_settings_dict = agent_vault_settings_instance.to_dict()
# create an instance of AgentVaultSettings from a dict
agent_vault_settings_from_dict = AgentVaultSettings.from_dict(agent_vault_settings_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


