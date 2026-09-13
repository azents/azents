# ExternalAccountOAuthFieldResponse

Redacted provider OAuth field projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **str** |  | 
**secret** | **bool** |  | 
**value** | **str** |  | 
**configured** | **bool** |  | 
**source** | [**SystemSettingFieldSource**](SystemSettingFieldSource.md) |  | 
**fallback_configured** | **bool** |  | 
**fallback_last_changed_at** | **datetime** |  | 

## Example

```python
from azentsadminclient.models.external_account_o_auth_field_response import ExternalAccountOAuthFieldResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalAccountOAuthFieldResponse from a JSON string
external_account_o_auth_field_response_instance = ExternalAccountOAuthFieldResponse.from_json(json)
# print the JSON string representation of the object
print(ExternalAccountOAuthFieldResponse.to_json())

# convert the object into a dict
external_account_o_auth_field_response_dict = external_account_o_auth_field_response_instance.to_dict()
# create an instance of ExternalAccountOAuthFieldResponse from a dict
external_account_o_auth_field_response_from_dict = ExternalAccountOAuthFieldResponse.from_dict(external_account_o_auth_field_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


