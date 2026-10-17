# PersonalOAuthExchangeRequest

Transient callback receipt with owner/target derived from trusted context.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**code** | **str** |  | 
**state** | **str** |  | 

## Example

```python
from azentspublicclient.models.personal_o_auth_exchange_request import PersonalOAuthExchangeRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalOAuthExchangeRequest from a JSON string
personal_o_auth_exchange_request_instance = PersonalOAuthExchangeRequest.from_json(json)
# print the JSON string representation of the object
print(PersonalOAuthExchangeRequest.to_json())

# convert the object into a dict
personal_o_auth_exchange_request_dict = personal_o_auth_exchange_request_instance.to_dict()
# create an instance of PersonalOAuthExchangeRequest from a dict
personal_o_auth_exchange_request_from_dict = PersonalOAuthExchangeRequest.from_dict(personal_o_auth_exchange_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


