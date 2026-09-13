# ExternalAccountOAuthHealthResponse

Provider OAuth health projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**SystemSettingHealthStatus**](SystemSettingHealthStatus.md) |  | 
**code** | **str** |  | 
**message** | **str** |  | 
**action_hint** | **str** |  | 
**checked_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.external_account_o_auth_health_response import ExternalAccountOAuthHealthResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalAccountOAuthHealthResponse from a JSON string
external_account_o_auth_health_response_instance = ExternalAccountOAuthHealthResponse.from_json(json)
# print the JSON string representation of the object
print(ExternalAccountOAuthHealthResponse.to_json())

# convert the object into a dict
external_account_o_auth_health_response_dict = external_account_o_auth_health_response_instance.to_dict()
# create an instance of ExternalAccountOAuthHealthResponse from a dict
external_account_o_auth_health_response_from_dict = ExternalAccountOAuthHealthResponse.from_dict(external_account_o_auth_health_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


