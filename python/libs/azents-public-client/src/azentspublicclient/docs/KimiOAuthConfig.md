# KimiOAuthConfig

Kimi OAuth display and status settings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'kimi_oauth']
**connection_method** | **str** | Connection method | 
**status** | **str** | Connection status | 
**connected_at** | **datetime** |  | 
**last_refreshed_at** | **datetime** |  | 
**last_failed_at** | **datetime** |  | 
**last_failure_reason** | **str** |  | 

## Example

```python
from azentspublicclient.models.kimi_o_auth_config import KimiOAuthConfig

# TODO update the JSON string below
json = "{}"
# create an instance of KimiOAuthConfig from a JSON string
kimi_o_auth_config_instance = KimiOAuthConfig.from_json(json)
# print the JSON string representation of the object
print(KimiOAuthConfig.to_json())

# convert the object into a dict
kimi_o_auth_config_dict = kimi_o_auth_config_instance.to_dict()
# create an instance of KimiOAuthConfig from a dict
kimi_o_auth_config_from_dict = KimiOAuthConfig.from_dict(kimi_o_auth_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


