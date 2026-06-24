# OAuthExchangeRequest

OAuth2 token exchange request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** | OAuth2 authorization code |
**state** | **str** | OAuth2 state parameter |

## Example

```python
from azentspublicclient.models.o_auth_exchange_request import OAuthExchangeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of OAuthExchangeRequest from a JSON string
o_auth_exchange_request_instance = OAuthExchangeRequest.from_json(json)
# print the JSON string representation of the object
print(OAuthExchangeRequest.to_json())

# convert the object into a dict
o_auth_exchange_request_dict = o_auth_exchange_request_instance.to_dict()
# create an instance of OAuthExchangeRequest from a dict
o_auth_exchange_request_from_dict = OAuthExchangeRequest.from_dict(o_auth_exchange_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
