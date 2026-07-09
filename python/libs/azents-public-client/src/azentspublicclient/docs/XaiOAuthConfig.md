# XaiOAuthConfig

xAI OAuth display and status settings.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'xai_oauth']
**account_id** | **str** |  | [optional] 
**email** | **str** |  | [optional] 
**connection_method** | **str** | Connection method | 
**status** | **str** | Connection status | 
**entitlement_status** | **str** |  | [optional] 
**connected_at** | **datetime** |  | [optional] 
**last_refreshed_at** | **datetime** |  | [optional] 
**last_failed_at** | **datetime** |  | [optional] 
**last_failure_reason** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.xai_o_auth_config import XaiOAuthConfig

# TODO update the JSON string below
json = "{}"
# create an instance of XaiOAuthConfig from a JSON string
xai_o_auth_config_instance = XaiOAuthConfig.from_json(json)
# print the JSON string representation of the object
print(XaiOAuthConfig.to_json())

# convert the object into a dict
xai_o_auth_config_dict = xai_o_auth_config_instance.to_dict()
# create an instance of XaiOAuthConfig from a dict
xai_o_auth_config_from_dict = XaiOAuthConfig.from_dict(xai_o_auth_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


